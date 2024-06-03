import streamlit as st
import boto3
import io
import requests
import base64
import json
import pandas as pd
from PIL import Image
from pillow_heif import register_heif_opener

# Set the page config as the first command
st.set_page_config(layout="wide")


register_heif_opener()
# Accessing credentials from environment variables
aws_access_key_id = st.secrets["AWS_ACCESS_KEY_ID"]
aws_secret_access_key = st.secrets["AWS_SECRET_ACCESS_KEY"]
aws_default_region = st.secrets["AWS_DEFAULT_REGION"]

# Boto3 clients
s3_client = boto3.client('s3',
    aws_access_key_id=aws_access_key_id, 
    aws_secret_access_key=aws_secret_access_key, 
    region_name=aws_default_region)
dynamodb = boto3.resource('dynamodb',
    aws_access_key_id=aws_access_key_id, 
    aws_secret_access_key=aws_secret_access_key, 
    region_name=aws_default_region)

# API URL
api_url = 'https://ijkv196dd9.execute-api.eu-west-1.amazonaws.com/dev/v1/upload'
# Parameters
user = "demoUser"

# S3 Bucket name
bucket_name = 'scan-me-images-bucket-dev'
# DynamoDB table name
table_name = 'scan-me-photo-metadata-dev'
# API URL for polling
api_poll_url = "https://ijkv196dd9.execute-api.eu-west-1.amazonaws.com/dev/v1/getTranscriptions"
# Parameters for the API call



# Streamlit layout
st.title('ScanMe')

company = st.text_input("Enter Your Company's Name (the tool will break if you don't assign a value)", "")

params = {"companyId": company}

def convert_image_to_jpeg(image_file, file_extension):
    if file_extension == 'heic':
        with Image.open(io.BytesIO(image_file)) as img:
            byte_arr = io.BytesIO()
            img.save(byte_arr, format='JPEG')
            return byte_arr
    else:
        return io.BytesIO(image_file)
    
# Function to make GET request to export data API
def get_presigned_url(company_id, user_id, export_format):
    api_url = f"https://ijkv196dd9.execute-api.eu-west-1.amazonaws.com/dev/v1/exportData?companyId={company_id}&user={user_id}&format={export_format}"
    response = requests.get(api_url)
    return response

# Function to send POST request to the API
def send_payload_to_api(payload, api_url):
    response = requests.post(api_url, json=payload)
    return response

def poll_data_from_api(api_url, params):
    response = requests.get(api_url, params=params)
    if response.ok:
        return response.json()
    else:
        raise Exception("Failed to fetch data from API")

# Function to process and categorize records
def categorize_records(records):
    data_for_table = {'pending': [], 'completed': [], 'failed': []}
    for record in records:
        status = record.get('status', 'N/A')

        # Handle transcription data based on status
        if status == 'pending':
            transcription_data = None
        elif status == 'failed':
            transcription_data = {"Error": record.get('transcription', "Unknown error")}
        else:
            transcription_data = parse_transcription_json(record.get('transcription', '{}'))

        # Add record to the appropriate category
        record_data = {
            "bucketKey": record.get('bucketKey', 'N/A'),
            "userId": record.get('userId', 'N/A'),
            "transcription": transcription_data
        }
        data_for_table[status].append(record_data)

    return data_for_table

# Function to poll and update the status of records
def fetch_and_process_data(api_url, params):
    response = requests.get(api_url, params=params)
    if response.ok:
        data = response.json()
        pending_records = []
        completed_records = []
        failed_records = []

        for record in data.get("transcriptions", []):
            status = record.get("status")
            transcription = json.loads(record.get("transcription", "{}"))

            if status == "pending":
                pending_records.append(transcription)
            elif status == "completed":
                completed_records.append(transcription)
            elif status == "failed":
                failed_records.append(transcription)

        return pending_records, completed_records, failed_records
    else:
        raise Exception("Failed to fetch data from API")

# Function to generate payload
def generate_payload(image_file, user, company, file_extension):
    encoded_image = base64.b64encode(image_file.getvalue()).decode('utf-8')

    padding = len(encoded_image) % 4
    if padding != 0:
        encoded_image += '=' * (4 - padding)

    payload = {
        "isBase64Encoded": True,
        "user": user,
        "companyId": company,
        "file_extension": file_extension,
        "image": encoded_image
    }

    return payload

# Function to parse the transcription JSON string
def parse_transcription_json(json_str):
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {"Error": "Invalid JSON format"}

# Streamlit layout for file upload
uploaded_files = st.file_uploader("Upload image(s)...", accept_multiple_files=True)

# Initialize session state variables if they don't exist
if 'files_uploaded' not in st.session_state:
    st.session_state['files_uploaded'] = False
if 'pending_records' not in st.session_state:
    st.session_state['pending_records'] = {}  # Dictionary to store pending records
if 'completed_data' not in st.session_state:
    st.session_state['completed_data'] = []  # List to store completed records data


# Button to send all payloads
if st.button('Upload All Images'):
    if uploaded_files:
        with st.spinner('Uploading images...'):
            success_count = 0
            for uploaded_file in uploaded_files:
                file_extension = uploaded_file.name.split('.')[-1].lower()
                image_bytes = convert_image_to_jpeg(uploaded_file.getvalue(), file_extension)
                payload = generate_payload(image_bytes, user, company, 'jpg' if file_extension == 'heic' else file_extension)
                response = send_payload_to_api(payload, api_url)
                if response.ok:
                    success_count += 1
                else:
                    st.error(f"Failed to upload {uploaded_file.name}. Error: {response.text}")

        st.success(f"Successfully uploaded {success_count} out of {len(uploaded_files)} images.")
        st.session_state['files_uploaded'] = True
    else:
        st.warning("No files to upload.")

# 'Poll Data' button
if st.session_state['files_uploaded'] or not uploaded_files:
    if st.button("Poll Data"):
        st.write("Polling data from API...")
        response = poll_data_from_api(api_poll_url, params=params)
        if response and "transcriptions" in response:
            categorized_data = categorize_records(response["transcriptions"])

            # Display Pending Records
            if categorized_data['pending']:
                st.subheader("Pending Records")
                st.write(pd.DataFrame(categorized_data['pending']))
            else:
                st.info("No pending records.")

            # Display Completed Records
            if categorized_data['completed']:
                st.subheader("Completed Records")
                completed_data = [record['transcription'] for record in categorized_data['completed'] if record['transcription']]
                if completed_data:  # Ensure there is data to display
                    completed_df = pd.DataFrame(completed_data)
                    st.dataframe(completed_df)
                else:
                    st.info("No completed records with transcription data.")
            else:
                st.info("No completed records.")

            # Display Failed Records
            if categorized_data['failed']:
                st.subheader("Failed Records")
                st.write(pd.DataFrame(categorized_data['failed']))
            else:
                st.info("No failed records.")
        else:
            st.error("Failed to retrieve data or no data available.")

# Dropdown for format selection
export_format = st.selectbox("Select export format:", ["xlsx", "csv"])
st.write("Exporting by xlsx, separates Sheets per Industry column.")
# Button for exporting data
if st.button('Export Data'):
    response = get_presigned_url(company, user, export_format)
    if response.ok:
        presigned_url = response.text  # Assuming the response text is the presigned URL
        st.markdown(f"[Download data as {export_format}]({presigned_url})")
    else:
        st.error("Failed to export data.")