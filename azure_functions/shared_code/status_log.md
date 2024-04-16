# Status Logger

To provide a simple and consumable status log to features such as the web UI, we output processing progress status to a log file for each file processed in Cosmos DB. This functionality is within the file called status_log.py. It creates a JSON document for each file processed and then updates as a new status item is achieved and by default, these files are in the Informaion_assistant database and the status container with it. Below is an example of a status document. The id is a base64 encoding of the file name. This is used as the partition key. The reason for the encoding is if the file name includes any invalid characters that would raise an error when trying to use as a partition key.

Currently the status logger provides a class, StatusLog, with the following functions:

- **upsert_document** - this function will insert or update a status entry in the Cosmos DB instance if you supply the document id and the status you wish to log. Please note the document id is generated using the encode_document_id function
- **encode_document_id** - this function is used to generate the id from the file name by the upsert_document function initially. It can also be called to retrieve the encoded id of a file if you pass in the file name. The id is used as the partition key.
- **read_documents** - This function returns status documents from Cosmos DB for you to use. You can specify optional query parameters, such as document id (the document path) or an integer representing how many minutes from now the processing should have started, or if you wish to receive verbose or concise details.

Finally you will need to supply 4 properties to the class before you can call the above functions. These are COSMOSDB_URL, COSMOSDB_KEY, COSMOSDB_LOG_DATABASE_NAME and COSMOSDB_LOG_CONTAINER_NAME. The resulting json includes verbos status updates but also a snapshot status for the end user UI, specifically the state, state_description and state_timestamp. These values are just select high level state snapshots, including 'Processing', 'Error' and 'Complete'.

````json
{
        "id": "dXBsb2FkL3VzZXJtay8yMDI0MDMxMTEyNDAvQU9BSU1vZGVxxxxxZGY=",
        "doc_type": "file_log",
        "file_path": "upload/userxyz/202403111240/AOAIModels.pdf",
        "file_name": "AOAIModels.pdf",
        "state": "Complete",
        "chunk_count": 46,
        "merged_chunk_count": 15,
        "start_timestamp": "2024-04-16 12:02:24",
        "state_description": "",
        "state_timestamp": "2024-04-16 12:08:05",
        "status_updates": [
            {
                "status": "Pipeline triggered by Blob Upload",
                "status_timestamp": "2024-04-16 12:02:24",
                "status_classification": "Info"
            },
            {
                "status": "AddToQueue - function started",
                "status_timestamp": "2024-04-16 12:02:24",
                "status_classification": "Debug"
            },
            {
                "status": "AddToQueue - pdf file sent to submit queue. Visible in 10 seconds",
                "status_timestamp": "2024-04-16 12:02:24",
                "status_classification": "Debug"
            },
            {
                "status": "SubmitToDocumentIntel - Received message from pdf-submit-queue ",
                "status_timestamp": "2024-04-16 12:02:37",
                "status_classification": "Debug"
            },
            {
                "status": "SubmitToDocumentIntel - Submitting to Form Recognizer",
                "status_timestamp": "2024-04-16 12:02:37",
                "status_classification": "Info"
            },
            {
                "status": "SubmitToDocumentIntel - SAS token generated",
                "status_timestamp": "2024-04-16 12:02:37",
                "status_classification": "Debug"
            },
            {
                "status": "Submitting to FR with url: https://xxxxx.cognitiveservices.azure.com/formrecognizer/documentModels/prebuilt-layout:analyze",
                "status_timestamp": "2024-04-16 12:02:37",
                "status_classification": "Debug"
            },
            {
                "status": "SubmitToDocumentIntel - PDF submitted to FR successfully",
                "status_timestamp": "2024-04-16 12:02:38",
                "status_classification": "Debug"
            },
            {
                "status": "SubmitToDocumentIntel - message sent to pdf-polling-queue. Visible in 10 seconds. FR Result ID is 29fcdcb6-77b7-4c38-91af-xxxxx",
                "status_timestamp": "2024-04-16 12:02:38",
                "status_classification": "Debug"
            },
            {
                "status": "PollDocumentIntelChunk - Message received from pdf polling queue attempt 1",
                "status_timestamp": "2024-04-16 12:02:53",
                "status_classification": "Debug"
            },
            {
                "status": "PollDocumentIntelChunk - Polling Form Recognizer function started",
                "status_timestamp": "2024-04-16 12:02:53",
                "status_classification": "Info"
            },
            {
                "status": "PollDocumentIntelChunk - Form Recognizer has completed processing and the analyze results have been received",
                "status_timestamp": "2024-04-16 12:02:54",
                "status_classification": "Debug"
            },
            {
                "status": "PollDocumentIntelChunk - Starting document map build",
                "status_timestamp": "2024-04-16 12:02:55",
                "status_classification": "Debug"
            },
            {
                "status": "PollDocumentIntelChunk - Document map build complete",
                "status_timestamp": "2024-04-16 12:02:55",
                "status_classification": "Debug"
            },
            {
                "status": "PollDocumentIntelChunk - Starting chunking",
                "status_timestamp": "2024-04-16 12:02:55",
                "status_classification": "Debug"
            },
            {
                "status": "PollDocumentIntelChunk - Chunking complete, 46 chunks created.",
                "status_timestamp": "2024-04-16 12:03:10",
                "status_classification": "Debug"
            },
            {
                "status": "PollDocumentIntelChunk - Starting chunk merging",
                "status_timestamp": "2024-04-16 12:03:10",
                "status_classification": "Debug"
            },
            {
                "status": "PollDocumentIntelChunk - Chunk merging complete, 15 merged chunks created with MERGED_CHUNK_TARGET_SIZE 512.",
                "status_timestamp": "2024-04-16 12:03:15",
                "status_classification": "Debug"
            },
            {
                "status": "PollDocumentIntelChunk - 15 merged chunks sent to chunks queue, prompt_id default.",
                "status_timestamp": "2024-04-16 12:03:18",
                "status_classification": "Debug"
            }
        ],
        "_rid": "KxxxxxcBaAMFfUvcWAAAAAAAAAA==",
        "_self": "dbs/KcBaAA==/colls/KcBaAMFfUvc=/docs/KcBaAMFfUvcWAAAAAAAAAA==/",
        "_etag": "\"d101688b-0000-1a00-0000-xxxxx\"",
        "_attachments": "attachments/",
        "_ts": 1713265685
    }
````
