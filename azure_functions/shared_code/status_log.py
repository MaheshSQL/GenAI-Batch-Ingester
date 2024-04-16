# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

""" Library of code for status logs reused across various calling features """
import os
from datetime import datetime, timedelta
import base64
from enum import Enum
import logging
from azure.cosmos import CosmosClient, PartitionKey, exceptions
import traceback, sys

class State(Enum):
    """ Enum for state of a process """
    PROCESSING = "Processing"
    SKIPPED = "Skipped"
    QUEUED = "Queued"
    COMPLETE = "Complete"
    ERROR = "Error"
    THROTTLED = "Throttled"
    UPLOADED = "Uploaded"
    ALL = "All"

class StatusClassification(Enum):
    """ Enum for classification of a status message """
    DEBUG = "Debug"
    INFO = "Info"
    ERROR = "Error"

class StatusQueryLevel(Enum):
    """ Enum for level of detail of a status query """
    CONCISE = "Concise"
    VERBOSE = "Verbose"


class StatusLog:
    """ Class for logging status of various processes to Cosmos DB"""

    def __init__(self, url, key, database_name, container_name):
        """ Constructor function """
        self._url = url
        self._key = key
        self._database_name = database_name
        self._container_name = container_name
        self.cosmos_client = CosmosClient(url=self._url, credential=self._key)
        self._log_document = {}

        # Select a database (will create it if it doesn't exist)
        self.database = self.cosmos_client.get_database_client(self._database_name)
        if self._database_name not in [db['id'] for db in self.cosmos_client.list_databases()]:
            self.database = self.cosmos_client.create_database(self._database_name)

        # Select a container (will create it if it doesn't exist)
        self.container = self.database.get_container_client(self._container_name)
        if self._container_name not in [container['id'] for container
                                        in self.database.list_containers()]:
            self.container = self.database.create_container(id=self._container_name,
                partition_key=PartitionKey(path="/file_name"))

    def encode_document_id(self, document_id):
        """ encode a path/file name to remove unsafe chars for a cosmos db id """
        safe_id = base64.urlsafe_b64encode(document_id.encode()).decode()
        return safe_id

    def read_file_status(self,
                       file_id: str,
                       status_query_level: StatusQueryLevel = StatusQueryLevel.CONCISE
                       ):
        """ 
        Function to issue a query and return resulting single doc        
        args
            status_query_level - the StatusQueryLevel value representing concise 
            or verbose status updates to be included
            file_id - if you wish to return a single document by its path     
        """
        query_string = f"SELECT * FROM c WHERE c.id = '{self.encode_document_id(file_id)}'"

        items = list(self.container.query_items(
            query=query_string,
            enable_cross_partition_query=True
        ))

        # Now we have the document, remove the status updates that are
        # considered 'non-verbose' if required
        if status_query_level == StatusQueryLevel.CONCISE:
            for item in items:
                # Filter out status updates that have status_classification == "debug"
                item['status_updates'] = [update for update in item['status_updates']
                                          if update['status_classification'] != 'Debug']

        return items


    def read_files_status_by_timeframe(self, 
                       within_n_hours: int,
                       state: State = State.ALL
                       ):
        """ 
        Function to issue a query and return resulting docs          
        args
            within_n_hours - integer representing from how many minutes ago to return docs for
        """

        query_string = "SELECT c.id,  c.file_path, c.file_name, c.state, \
            c.start_timestamp, c.state_description, c.state_timestamp \
            FROM c"

        conditions = []    
        if within_n_hours != -1:
            from_time = datetime.utcnow() - timedelta(hours=within_n_hours)
            from_time_string = str(from_time.strftime('%Y-%m-%d %H:%M:%S'))
            conditions.append(f"c.start_timestamp > '{from_time_string}'")

        if state != State.ALL:
            conditions.append(f"c.state = '{state.value}'")

        if conditions:
            query_string += " WHERE " + " AND ".join(conditions)

        query_string += " ORDER BY c.state_timestamp DESC"

        items = list(self.container.query_items(
            query=query_string,
            enable_cross_partition_query=True
        ))

        return items

    # Updated
    def upsert_document(self, document_path, status, status_classification: StatusClassification,
                        state=State.PROCESSING, fresh_start=False, chunk_count = None, merged_chunk_count = None ):
        """ Function to upsert a status item for a specified id """
        base_name = os.path.basename(document_path)
        document_id = self.encode_document_id(document_path)

        # add status to standard logger
        logging.info(f"{status} DocumentID - {document_id}")

        # If this event is the start of an upload, remove any existing status files for this path
        if fresh_start:
            try:
                self.container.delete_item(item=document_id, partition_key=base_name)
            except exceptions.CosmosResourceNotFoundError:
                pass

        json_document = ""
        try:
            # if the document exists and if this is the first call to the function from the parent,
            # then retrieve the stored document from cosmos, otherwise, use the log stored in self
            if self._log_document.get(document_id, "") == "":
                json_document = self.container.read_item(item=document_id, partition_key=base_name)
            else:
                json_document = self._log_document[document_id]

            # Check if there has been a state change, and therefore to update state
            if json_document['state'] != state.value:
                json_document['state'] = state.value
                json_document['state_timestamp'] = str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

            # New
            # Check if there chunk_count and merged_chunk_count are provided to update after chunking and merging chunks
            if chunk_count and json_document['chunk_count'] != chunk_count:
                json_document['chunk_count'] = chunk_count
            if merged_chunk_count and json_document['merged_chunk_count'] != merged_chunk_count:
                json_document['merged_chunk_count'] = merged_chunk_count

            # Append a new item to the array
            status_updates = json_document["status_updates"]
            new_item = {
                "status": status,
                "status_timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                "status_classification": str(status_classification.value)
            }

            if status_classification == StatusClassification.ERROR:
                new_item["stack_trace"] = self.get_stack_trace()

            status_updates.append(new_item)
        except exceptions.CosmosResourceNotFoundError:
            # this is a new document
            json_document = {
                "id": document_id,
                "doc_type": "file_log",
                "file_path": document_path,
                "file_name": base_name,
                "state": str(state.value),
                "chunk_count": -1, # Will be updated by chunking step
                "merged_chunk_count": -1, # Will be updated by chunking step
                "start_timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                "state_description": "",
                "state_timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                "status_updates": [
                    {
                        "status": status,
                        "status_timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                        "status_classification": str(status_classification.value)
                    }
                ]
            }
        except Exception:
            # log the exception with stack trace to the status log
            json_document = {
                "id": document_id,
                "doc_type": "file_log",
                "file_path": document_path,
                "file_name": base_name,
                "state": str(state.value),
                "chunk_count": -1, # Will be updated by chunking step
                "merged_chunk_count": -1,# Will be updated by chunking step
                "start_timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                "state_description": "",
                "state_timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                "status_updates": [
                    {
                        "status": status,
                        "status_timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                        "status_classification": str(status_classification.value),
                        "stack_trace": self.get_stack_trace() if not fresh_start else None
                    }
                ]
            }

        #self.container.upsert_item(body=json_document)
        self._log_document[document_id] = json_document

    # Updated, bug fixed
    def update_document_state(self, document_path, state_str):
        """Updates the state of the document in the storage"""
        try:
            base_name = os.path.basename(document_path)            
            document_id = self.encode_document_id(document_path)

            # if the document exists and if this is the first call to the function from the parent,
            # then retrieve the stored document from cosmos, otherwise, use the log stored in self
            if self._log_document.get(document_id, "") == "":
                json_document = self.container.read_item(item=document_id, partition_key=base_name)
                self._log_document[document_id] = json_document            

            logging.info(f"{state_str} DocumentID - {document_id}")
            # document_id = self.encode_document_id(document_path)
            if self._log_document.get(document_id, "") != "":
                json_document = self._log_document[document_id]
                json_document['state'] = state_str
                json_document['state_timestamp'] = str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                self.save_document(document_path)
                self._log_document[document_id] = json_document
            else:
                logging.warning(f"Document with ID {document_id} not found.")
        except Exception as err:
            logging.error(f"An error occurred while updating the document state: {str(err)}")      

    def save_document(self, document_path):
        """Saves the document in the storage"""
        document_id = self.encode_document_id(document_path)
        self.container.upsert_item(body=self._log_document[document_id])
        self._log_document[document_id] = ""

    def get_stack_trace(self):
        """ Returns the stack trace of the current exception"""
        exc = sys.exc_info()[0]
        stack = traceback.extract_stack()[:-1]  # last one would be full_stack()
        if exc is not None:  # i.e. an exception is present
            del stack[-1]       # remove call of full_stack, the printed exception
                                # will contain the caught exception caller instead
        trc = 'Traceback (most recent call last):\n'
        stackstr = trc + ''.join(traceback.format_list(stack))
        if exc is not None:
            stackstr += '  ' + traceback.format_exc().lstrip(trc)
        return stackstr

    # New
    def create_chunk_log_entry(self, file_path, chunk_blob_uri, chunk_name, chunk_state, additional_info = ""):

            base_name = os.path.basename(file_path)
            document_id = self.encode_document_id(chunk_name)

            json_data = {
                "id": document_id,
                "doc_type": "chunk_log",
                "file_path": file_path,
                "file_name": base_name,
                "chunk_name": chunk_name,
                "chunk_state": chunk_state.value,
                # "chunk_blob_uri": chunk_blob_uri,
                "state_timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                "Addtional info": additional_info
            }

            # print(f'json_data:{json_data}')

            """Saves the document in the storage"""        
            self.container.upsert_item(body=json_data)

    # New
    def create_llm_output_entry(self, file_path, chunk_blob_uri, chunk_name, llm_output, llm_output_file, user_id, prompt_id, llm_completion_tokens, llm_prompt_tokens, llm_total_tokens):

            base_name = os.path.basename(file_path)
            document_id = self.encode_document_id(llm_output_file)
            # print(f'document_id:{llm_output_file}')
            # print(f'document_id:{document_id}')

            json_data = {
                "id": document_id,
                "doc_type": "llm_output",
                "file_path": file_path,
                "file_name": base_name,
                "chunk_name": chunk_name, 
                "llm_output": llm_output,
                "llm_output_file": llm_output_file,                
                "user_id": user_id,
                "prompt_id": prompt_id,
                "llm_completion_tokens": llm_completion_tokens,
                "llm_prompt_tokens": llm_prompt_tokens,
                "llm_total_tokens": llm_total_tokens,
                "state_timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))                
            }

            # print(f'json_data:{json_data}')

            """Saves the document in the storage"""        
            self.container.upsert_item(body=json_data)

    # New
    def mark_document_processing_complete(self,
                       file_path: str ):
        """
        Function checks and then marks document processing complete once all chunks have been processed for the document.
        """

        # print(f'In update_document_processing_state(), file_path:{file_path}')        
        
        #-------------------------------------------------------------------#
        # Chunks to be processed (merged_chunk_count)
        query_string_total_chunk_count = f"SELECT VALUE a.merged_chunk_count FROM a WHERE a.doc_type = 'file_log' and a.file_path = '{file_path}'"        
        # print(f'query_string_total_chunk_count:{query_string_total_chunk_count}')
        items = list(self.container.query_items(query=query_string_total_chunk_count,
                        enable_cross_partition_query=True))
        # print(f'mark_document_processing_complete() -> items:{items}, type(items):{type(items)}')
        
        total_chunk_count = 0
        if items and len(items) > 0:
            total_chunk_count = int(items[0])

        #-------------------------------------------------------------------#
        # Chunks processed so far        
        query_string_processed_chunk_count = f"SELECT  VALUE COUNT(1) FROM c WHERE c.doc_type = 'chunk_log' AND c.file_path = '{file_path}' AND c.chunk_state  = 'Complete'"
        # print(f'query_string_processed_chunk_count:{query_string_processed_chunk_count}')
        processed_items = list(self.container.query_items(query=query_string_processed_chunk_count,
                        enable_cross_partition_query=True))
        # print(f'mark_document_processing_complete() -> processed_items:{processed_items}, type(processed_items):{type(processed_items)}')
        
        processed_chunk_count = 0
        if processed_items and len(processed_items) > 0:
            processed_chunk_count = int(processed_items[0])
        
        if total_chunk_count==processed_chunk_count:
            self.update_document_state(file_path, State.COMPLETE.value) #Mark as processing completed for the parent document
    

# New
class PromptLog:
    """ Class for fetching prompt metadata and logging prompt outputs to Cosmos DB"""

    def __init__(self, url, key, database_name, container_name):
        """ Constructor function """
        self._url = url
        self._key = key
        self._database_name = database_name
        self._container_name = container_name
        self.cosmos_client = CosmosClient(url=self._url, credential=self._key)
        self._log_document = {}

        # Select a database (will create it if it doesn't exist)
        self.database = self.cosmos_client.get_database_client(self._database_name)
        if self._database_name not in [db['id'] for db in self.cosmos_client.list_databases()]:
            self.database = self.cosmos_client.create_database(self._database_name)

        # Select a container (will create it if it doesn't exist)
        self.container = self.database.get_container_client(self._container_name)
        if self._container_name not in [container['id'] for container
                                        in self.database.list_containers()]:
            self.container = self.database.create_container(id=self._container_name,
                partition_key=PartitionKey(path="/userid"))
            
            #Insert default prompt
            document_id = base64.urlsafe_b64encode('default'.encode()).decode()
            json_data = {
                "id": document_id,
                "userid": "default", 
                 "prompts": [
                                {
                                    "prompt_id": "default",
                                    "prompt": "Summarise the provided text below:"
                                }
                            ],            
                "timestamp": str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))                
            }

            # print(f'json_data:{json_data}')

            """Saves the document in the cosmosdb"""        
            self.container.upsert_item(body=json_data)

    def get_prompt(self,
                       user_id: str,
                       prompt_id: str
                       ):
        """
        Function to get prompt value (including default prompt) based on userid and prompt_id
        """

        # print(f'In get_prompt(), userid:{user_id}, prompt_id:{prompt_id}')
        
        query_string = f'SELECT c.prompts FROM c WHERE c.userid = "{user_id}" AND ARRAY_CONTAINS(c.prompts, {{ "prompt_id": "{prompt_id}"  }}, true)'
        # print(f'query_string:{query_string}')

        items = list(self.container.query_items(
            query=query_string,
            enable_cross_partition_query=True
        ))

        # print(f'get_prompt() -> items:{items}, type(items):{type(items)}')

        prompt_out = ""

        if items and len(items) > 0:

            # items = [{'prompts': [{'prompt_id': '1', 'prompt': 'Summarise the provided text below:'}, {'prompt_id': '2', 'prompt': 'Summarise the provided text below as bullet points:'}]}]
            # Get the prompt matching supplied prompt_id
            for prompt in items[0]["prompts"]:            
                if prompt["prompt_id"] == prompt_id:
                    prompt_out = prompt["prompt"]
                    break

        return prompt_out
    
    
    

