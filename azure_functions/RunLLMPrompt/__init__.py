# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import azure.functions as func
from azure.storage.queue import QueueClient, TextBase64EncodePolicy
import logging
import os
import json
import requests
from azure.storage.queue import QueueClient, TextBase64EncodePolicy
from shared_code.status_log import StatusLog, State, StatusClassification, PromptLog # New
from shared_code.utilities import Utilities, MediaType
import random
from collections import namedtuple
import time
from requests.exceptions import RequestException
from tenacity import retry, stop_after_attempt, wait_fixed

import requests # New

def string_to_bool(s):
    return s.lower() == 'true'

azure_blob_storage_account = os.environ["BLOB_STORAGE_ACCOUNT"]
azure_blob_storage_endpoint = os.environ["BLOB_STORAGE_ACCOUNT_ENDPOINT"]
azure_blob_drop_storage_container = os.environ["BLOB_STORAGE_ACCOUNT_UPLOAD_CONTAINER_NAME"]
azure_blob_content_storage_container = os.environ["BLOB_STORAGE_ACCOUNT_OUTPUT_CONTAINER_NAME"]
azure_blob_storage_key = os.environ["AZURE_BLOB_STORAGE_KEY"]
azure_blob_connection_string = os.environ["BLOB_CONNECTION_STRING"]
azure_blob_log_storage_container = os.environ["BLOB_STORAGE_ACCOUNT_LOG_CONTAINER_NAME"]
CHUNK_TARGET_SIZE = int(os.environ["CHUNK_TARGET_SIZE"])
MERGED_CHUNK_TARGET_SIZE = int(os.environ["MERGED_CHUNK_TARGET_SIZE"]) # New
FR_API_VERSION = os.environ["FR_API_VERSION"]
# ALL or Custom page numbers for multi-page documents(PDF/TIFF). Input the page numbers and/or
# ranges of pages you want to get in the result. For a range of pages, use a hyphen, like pages="1-3, 5-6".
# Separate each page number or range with a comma.
azure_blob_connection_string = os.environ["BLOB_CONNECTION_STRING"]
cosmosdb_url = os.environ["COSMOSDB_URL"]
cosmosdb_key = os.environ["COSMOSDB_KEY"]
cosmosdb_log_database_name = os.environ["COSMOSDB_LOG_DATABASE_NAME"]
cosmosdb_log_container_name = os.environ["COSMOSDB_LOG_CONTAINER_NAME"]
non_pdf_submit_queue = os.environ["NON_PDF_SUBMIT_QUEUE"]
pdf_polling_queue = os.environ["PDF_POLLING_QUEUE"]
pdf_submit_queue = os.environ["PDF_SUBMIT_QUEUE"]
# text_enrichment_queue = os.environ["TEXT_ENRICHMENT_QUEUE"]
endpoint = os.environ["AZURE_FORM_RECOGNIZER_ENDPOINT"]
FR_key = os.environ["AZURE_FORM_RECOGNIZER_KEY"]
api_version = os.environ["FR_API_VERSION"]
max_submit_requeue_count = int(os.environ["MAX_SUBMIT_REQUEUE_COUNT"])
max_polling_requeue_count = int(os.environ["MAX_POLLING_REQUEUE_COUNT"])
submit_requeue_hide_seconds = int(os.environ["SUBMIT_REQUEUE_HIDE_SECONDS"])
polling_backoff = int(os.environ["POLLING_BACKOFF"])
max_read_attempts = int(os.environ["MAX_READ_ATTEMPTS"])
enableDevCode = string_to_bool(os.environ["ENABLE_DEV_CODE"])

chunks_queue = os.environ["CHUNKS_QUEUE"]
max_seconds_hide_on_upload = int(os.environ["MAX_SECONDS_HIDE_ON_UPLOAD"])

# New
cosmosdb_prompt_database_name = os.environ["COSMOSDB_PROMPT_DATABASE_NAME"] #Prompt config
cosmosdb_prompt_container_name = os.environ["COSMOSDB_PROMPT_CONTAINER_NAME"] #Prompt config
cosmosdb_prompt_output_database_name = os.environ["COSMOSDB_PROMPT_OUTPUT_DATABASE_NAME"] #Prompt outputs
cosmosdb_prompt_output_container_name = os.environ["COSMOSDB_PROMPT_OUTPUT_CONTAINER_NAME"] #Prompt outputs
azure_openai_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
azure_openai_key = os.environ["AZURE_OPENAI_KEY"]
azure_openai_deployment_id = os.environ["AZURE_OPENAI_DEPLOYMENT_ID"]
azure_openai_api_version = os.environ["AZURE_OPENAI_API_VERSION"]
azure_openai_temperature = os.environ["AZURE_OPENAI_TEMPERATURE"]
azure_openai_top_p = os.environ["AZURE_OPENAI_TOP_P"]
azure_openai_max_tokens = os.environ["AZURE_OPENAI_MAX_TOKENS"]
azure_openai_system_message = os.environ["AZURE_OPENAI_SYSTEM_MESSAGE"]


function_name = "RunLLMPrompt"
utilities = Utilities(azure_blob_storage_account, azure_blob_storage_endpoint, azure_blob_drop_storage_container, azure_blob_content_storage_container, azure_blob_storage_key)
FR_MODEL = "prebuilt-layout"


def main(msg: func.QueueMessage) -> None:
    '''This function is triggerred by message in the chunks-queue.
    The queue message contains merged chunk file blob uri. This function applies the default prompt to the merged chunk text and saves the output in CosmosDB.
    The default prompt is taken from the the CosmosDB.
    '''
    
    try:
        statusLog = StatusLog(cosmosdb_url, cosmosdb_key, cosmosdb_log_database_name, cosmosdb_log_container_name)
        promptLog = PromptLog(cosmosdb_url, cosmosdb_key, cosmosdb_prompt_database_name, cosmosdb_prompt_container_name)
        

        # Receive message from the queue
        message_body = msg.get_body().decode('utf-8')
        message_json = json.loads(message_body)
        blob_name =  message_json['blob_name']
        blob_uri =  message_json['blob_uri']        
        chunk_name = message_json["chunk_name"]
        chunk_blob_uri =  message_json['chunk_blob_uri']
        FR_resultId = message_json['FR_resultId']
        queued_count = message_json['polling_queue_count']      
        submit_queued_count = message_json["submit_queued_count"]
        chunk_queued_count = message_json["chunk_queued_count"]
        prompt_id = message_json["prompt_id"]
       
        
        # statusLog.upsert_document(blob_name, f'{function_name} - Message received from chunks-queue attempt {chunk_queued_count}', StatusClassification.DEBUG, State.PROCESSING)        
        # statusLog.upsert_document(blob_name, f'{function_name} - Call to Azure OpenAI endpoint started for chunk {chunk_name}', StatusClassification.INFO)
        statusLog.create_chunk_log_entry(blob_name,chunk_blob_uri,chunk_name,State.PROCESSING, f'{function_name} - Processing started')        

        # TO DO
        # 1. Retrieve prompt from CosmosDB based on prompt_id from queue message - DONE
        # 2. Add AOAI endpoint details as environment variables - DONE
        # 3. Submit request to AOAI endpoint (REST)
        # 4. Save results back to CosmosDB
        # 5. Handle throttling / requeue

        #  blob_uri:https://xxxxx.blob.core.windows.net/upload/usermk/202403111240/WhatIsAOAI.pdf
        # print(f'blob_uri:{blob_uri}')

        # Default user_id
        user_id = "default"

        # If prompt_id is other than "default" then use user_id who uploaded the file
        # This will be functionality for future use where a user can use their own prompts saved in cosmosdb
        if prompt_id != "default":
            user_id = blob_uri.split('/')[4] #Extract username from path
            # print(f'user_id:{user_id}')

        # Retrieve prompt from CosmosDB based on prompt_id from queue message
        # default prompt for default user_id fetched when prompt_id = prompt_id, otherwise based on prompt_id for corresponding user_id
        prompt = promptLog.get_prompt(user_id, prompt_id)
        # print(f'prompt: {prompt}')

        # Retrieve merged chunk from the blob
        # print(f'chunk_blob_uri:{chunk_blob_uri}')

        input_text = "" # TO DO
        blob_content = ""
        blob_content_json = {}

        blob_content = utilities.read_blob_content(chunk_name, chunk_blob_uri).decode('utf-8') # Decoding the byte string
        # print(f'blob_content:{blob_content}')

        blob_content_json = json.loads(blob_content)
        # print(f'blob_content_json:{blob_content_json}')

        input_text = blob_content_json["merged_content"]
        # print(f'input_text:{input_text}')

        # Submit request to AOAI chat completion endpoint (REST)

        # Expected format: https://{your-resource-name}.openai.azure.com/openai/deployments/{deployment-id}/chat/completions?api-version={api-version}
        endpoint = f'{azure_openai_endpoint}/openai/deployments/{azure_openai_deployment_id}/chat/completions?api-version={azure_openai_api_version}'

        headers = {  
            "Content-Type": "application/json",  
            "api-key": azure_openai_key
            }  
        
        data = {
            "messages":[
                    {"role":"system","content":azure_openai_system_message},
                    {"role":"user","content":prompt+"\ninput text:"+ input_text}
                 ],
            "temperature": float(azure_openai_temperature),
            "top_p": float(azure_openai_top_p),
            "max_tokens": int(azure_openai_max_tokens)
        }

        # print(f'data:{data}')

        response = requests.post(endpoint, headers=headers, json=data)
        # print(f'response.status_code:{response.status_code}')
        # print(f'response:{response.content}')        

        # Success
        if response.status_code == 200:
            response_json = response.json()
            # print(f'response_json:{response_json}')
            # print(f'response_json["choices"][0]:{response_json["choices"][0]}')            

            if response_json["choices"][0]["finish_reason"] == 'stop':
                llm_output = response_json["choices"][0]["message"]["content"]
                llm_completion_tokens = response_json["usage"]["completion_tokens"]
                llm_prompt_tokens = response_json["usage"]["prompt_tokens"]
                llm_total_tokens = response_json["usage"]["total_tokens"]
                # print(f'llm_output:{llm_output}, llm_completion_tokens:{llm_completion_tokens}, llm_prompt_tokens:{llm_prompt_tokens}, llm_total_tokens:{llm_total_tokens}')
                
                # Save outputs to storage account
                llm_output_name, llm_output_blob_uri = utilities.write_llm_output(blob_name, blob_uri, blob_content_json["token_count"], blob_content_json["merged_content"], blob_content_json["pages"],
                                            blob_content_json["merged_file_names"], blob_content_json["merged_file_uris"], blob_content_json["file_class"], 
                                            chunk_name, chunk_blob_uri, prompt_id, response_json, output_content_dir = "llm")
                
                # print(f'llm_output_name:{llm_output_name}, llm_output_blob_uri:{llm_output_blob_uri}')

                # Save outputs to CosmosDB
                statusLog.create_llm_output_entry(blob_name, chunk_blob_uri, chunk_name, llm_output, llm_output_name, user_id, prompt_id, llm_completion_tokens, llm_prompt_tokens, llm_total_tokens)
                
                # statusLog.upsert_document(blob_name, f'{function_name} - Call to Azure OpenAI endpoint completed for chunk {chunk_name}, outputs saved. llm_completion_tokens: {llm_completion_tokens}, llm_prompt_tokens: {llm_prompt_tokens}, llm_total_tokens: {llm_total_tokens}', StatusClassification.INFO)
                statusLog.create_chunk_log_entry(blob_name,chunk_blob_uri,chunk_name,State.COMPLETE, f'{function_name} - llm_completion_tokens: {llm_completion_tokens}, llm_prompt_tokens: {llm_prompt_tokens}, llm_total_tokens: {llm_total_tokens}')
                
                # If all chunks are processed, mark document processing complete
                statusLog.mark_document_processing_complete(blob_name)
                

            elif response_json["choices"][0]["finish_reason"] == 'content_filter':
                # statusLog.upsert_document(blob_name, f"{function_name} - An error occurred, AOAI returned status code {response.status_code} with finish_reason = content_filter, input_text: {input_text}, response: {str(response.content)}", StatusClassification.DEBUG, State.PROCESSING)
                statusLog.create_chunk_log_entry(blob_name,chunk_blob_uri,chunk_name,State.SKIPPED, f'{function_name} - content_filter')

        # Re-queue
        elif response.status_code == 429:
            # unexpected status returned by FR, such as internal capacity overload, so requeue
            if chunk_queued_count < max_submit_requeue_count:
                # statusLog.upsert_document(blob_name, f'{function_name} - 429 response from Azure OpenAI endpoint - code: {response.status_code}, response.content: {response.content}. Request will be resubmitted', StatusClassification.ERROR)                  
                queue_client = QueueClient.from_connection_string(azure_blob_connection_string, chunks_queue, message_encode_policy=TextBase64EncodePolicy())  
                chunk_queued_count += 1
                message_json["chunk_queued_count"] = chunk_queued_count
                message_string = json.dumps(message_json)    
                queue_client.send_message(message_string, visibility_timeout = submit_requeue_hide_seconds)  
                # statusLog.upsert_document(blob_name, f'{function_name} chunk {chunk_name} resent to chunks queue. Visible in {submit_requeue_hide_seconds} seconds', StatusClassification.DEBUG, State.THROTTLED)      
                statusLog.create_chunk_log_entry(blob_name,chunk_blob_uri,chunk_name,State.THROTTLED, f'{function_name} - Re-queued, chunk_queued_count {chunk_queued_count},visible in {submit_requeue_hide_seconds} seconds')
            else:
                # statusLog.upsert_document(blob_name, f'{function_name} - maximum submissions to Azure OpenAI endpoint reached', StatusClassification.ERROR, State.ERROR)
                statusLog.create_chunk_log_entry(blob_name,chunk_blob_uri,chunk_name,State.ERROR, f'{function_name} - maximum submissions to Azure OpenAI endpoint reached')

        elif response.status_code == 400:
            # statusLog.upsert_document(blob_name, f"{function_name} - An error occurred, check your request payload, AOAI returned status code: {response.status_code}, {str(response.content)}", StatusClassification.ERROR, State.ERROR) 
            statusLog.create_chunk_log_entry(blob_name,chunk_blob_uri,chunk_name,State.ERROR, f'{function_name} - An error occurred, check your request payload, AOAI returned status_code: {response.status_code}, {str(response.content)}')
        
                            
    except Exception as e:
        print(f'Error str(e):{str(e)}')
        # a general error 
        # statusLog.upsert_document(blob_name, f"{function_name} - An error occurred - {str(e)}", StatusClassification.ERROR, State.ERROR)
        statusLog.create_chunk_log_entry(blob_name,chunk_blob_uri,chunk_name,State.ERROR, f'{function_name} - An error occurred in python code, str(e) - {str(e)}, message_json:{json.dumps(message_json)}')
        
        
    # statusLog.save_document(blob_name)


@retry(stop=stop_after_attempt(max_read_attempts), wait=wait_fixed(5))
def durable_get(url, headers, params):
    response = requests.get(url, headers=headers, params=params)   
    response.raise_for_status()  # Raise stored HTTPError, if one occurred.
    return response
