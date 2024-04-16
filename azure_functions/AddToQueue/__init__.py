# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import os
import json
import random
import time
from shared_code.status_log import StatusLog, State, StatusClassification
import azure.functions as func
from azure.storage.blob import generate_blob_sas
from azure.storage.queue import QueueClient, TextBase64EncodePolicy

from shared_code.utilities import Utilities, MediaType

azure_blob_storage_account = os.environ["BLOB_STORAGE_ACCOUNT"]
azure_blob_storage_endpoint = os.environ["BLOB_STORAGE_ACCOUNT_ENDPOINT"]
azure_blob_drop_storage_container = os.environ["BLOB_STORAGE_ACCOUNT_UPLOAD_CONTAINER_NAME"]
azure_blob_content_storage_container = os.environ["BLOB_STORAGE_ACCOUNT_OUTPUT_CONTAINER_NAME"]
azure_blob_storage_key = os.environ["AZURE_BLOB_STORAGE_KEY"]
azure_blob_connection_string = os.environ["BLOB_CONNECTION_STRING"]

azure_blob_connection_string = os.environ["BLOB_CONNECTION_STRING"]
cosmosdb_url = os.environ["COSMOSDB_URL"]
cosmosdb_key = os.environ["COSMOSDB_KEY"]
cosmosdb_log_database_name = os.environ["COSMOSDB_LOG_DATABASE_NAME"]
cosmosdb_log_container_name = os.environ["COSMOSDB_LOG_CONTAINER_NAME"]
non_pdf_submit_queue = os.environ["NON_PDF_SUBMIT_QUEUE"]

pdf_submit_queue = os.environ["PDF_SUBMIT_QUEUE"]
# media_submit_queue = os.environ["MEDIA_SUBMIT_QUEUE"]
# image_enrichment_queue = os.environ["IMAGE_ENRICHMENT_QUEUE"]
max_seconds_hide_on_upload = int(os.environ["MAX_SECONDS_HIDE_ON_UPLOAD"])
function_name = "AddToQueue"


def main(myblob: func.InputStream):
    """ Function to read supported file types and pass to the correct queue for processing"""

    try:
        time.sleep(random.randint(1, 2))  # add a random delay

        # New
        # Get blob metadata (if present). prompt_id is expected here set on blob while upload to storage.
        # If prompt_id is missing, then set it to "default". The prompt to be applied to text will be looked up from CosmosDB based on this prompt_id
        utilities = Utilities(azure_blob_storage_account, azure_blob_storage_endpoint, azure_blob_drop_storage_container, azure_blob_content_storage_container, azure_blob_storage_key)
        blob_metadata = utilities.get_blob_metadata(myblob.name, myblob.uri)
        # print(f"blob_metadata:{blob_metadata}")
        prompt_id = "default" # As set in CosmosDB
        # Check if prompt_id is present in the blob metadata which is proxy to prompt to run, otherwise it is defaulted to value set above.
        if "prompt_id" in blob_metadata:
            prompt_id = blob_metadata["prompt_id"]

        statusLog = StatusLog(cosmosdb_url, cosmosdb_key, cosmosdb_log_database_name, cosmosdb_log_container_name)
        statusLog.upsert_document(myblob.name, 'Pipeline triggered by Blob Upload', StatusClassification.INFO, State.PROCESSING, True) # Fresh start set to True, will delete existing log            
        statusLog.upsert_document(myblob.name, f'{function_name} - function started', StatusClassification.DEBUG)    
        
        # Create message structure to send to queue
      
        file_extension = os.path.splitext(myblob.name)[1][1:].lower()
        if file_extension == 'pdf':
             # If the file is a PDF a message is sent to the PDF processing queue.
            queue_name = pdf_submit_queue
  
        elif file_extension in ['htm', 'csv', 'doc', 'docx', 'eml', 'html', 'md', 'msg', 'ppt', 'pptx', 'txt', 'xlsx', 'xml', 'json']:
            # Else a message is sent to the non PDF processing queue
            queue_name = non_pdf_submit_queue
            
        # elif file_extension in ['flv', 'mxf', 'gxf', 'ts', 'ps', '3gp', '3gpp', 'mpg', 'wmv', 'asf', 'avi', 'wmv', 'mp4', 'm4a', 'm4v', 'isma', 'ismv', 'dvr-ms', 'mkv', 'wav', 'mov']:
        #     # Else a message is sent to the Media processing queue
        #     queue_name = media_submit_queue
        
        # elif file_extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tif', 'tiff']:
        #     # Else a message is sent to the Image processing queue
        #     queue_name = image_enrichment_queue
                 
        else:
            # Unknown file type
            logging.info("Unknown file type")
            error_message = f"{function_name} - Unexpected file type submitted {file_extension}"
            statusLog.state_description = error_message
            statusLog.upsert_document(myblob.name, error_message, StatusClassification.ERROR, State.SKIPPED) 
        
        # Create message
        message = {
            "blob_name": f"{myblob.name}",
            "blob_uri": f"{myblob.uri}",
            "submit_queued_count": 1,
            "prompt_id": prompt_id
        }        
        message_string = json.dumps(message)
        # print(f"message:{message}")
        
        # Queue message with a random backoff so as not to put the next function under unnecessary load
        queue_client = QueueClient.from_connection_string(azure_blob_connection_string, queue_name, message_encode_policy=TextBase64EncodePolicy())
        backoff =  random.randint(1, max_seconds_hide_on_upload)        
        queue_client.send_message(message_string, visibility_timeout = backoff)  
        statusLog.upsert_document(myblob.name, f'{function_name} - {file_extension} file sent to submit queue. Visible in {backoff} seconds', StatusClassification.DEBUG, State.QUEUED)          
        
    except Exception as err:
        statusLog.upsert_document(myblob.name, f"{function_name} - An error occurred - {str(err)}", StatusClassification.ERROR, State.ERROR)

    statusLog.save_document(myblob.name)