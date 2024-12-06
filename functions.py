import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os
import pandas as pd
import fitz
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from PIL import Image
from pdf2image import convert_from_bytes
from io import BytesIO
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(filename='certificate_process.log', level=logging.ERROR,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables


creds = Credentials.from_service_account_info(
    {
        "type": "service_account",
        "project_id": os.getenv("GOOGLE_PROJECT_ID"),
        "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
        "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace('\\n', '\n'),
        "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('GOOGLE_CLIENT_EMAIL')}"
    }
)

# Function to generate a preview of the certificate
def generate_preview(presentation_id, full_name):
    drive_service = build('drive', 'v3', credentials=creds)
    slides_service = build('slides', 'v1', credentials=creds)

    # Create a copy of the presentation for preview
    presentation_copy = drive_service.files().copy(
        fileId=presentation_id,
        body={'name': f'Preview_{full_name}'}
    ).execute()
    copied_presentation_id = presentation_copy['id']

    try:
        # Replace placeholders in the copied presentation
        slides_service.presentations().batchUpdate(
            presentationId=copied_presentation_id,
            body={
                'requests': [{
                    'replaceAllText': {
                        'containsText': {
                            'text': '{{Full_Name}}',
                            'matchCase': True
                        },
                        'replaceText': full_name
                    }
                }]
            }
        ).execute()

        # Export the presentation as a PDF
        export_url = f"https://www.googleapis.com/drive/v3/files/{copied_presentation_id}/export?mimeType=application/pdf"
        response, content = drive_service._http.request(export_url)

        if response.status != 200:
            raise Exception(f"Failed to export presentation as PDF: {response.reason}")

        # Load PDF content into PyMuPDF
        pdf_document = fitz.open(stream=content, filetype="pdf")
        page = pdf_document[0]  # Get the first slide (page)

        # Render the page as an image
        pix = page.get_pixmap(dpi=300)  # Higher DPI for better quality
        image_data = pix.tobytes("jpg")  # Return the image data as a file-like object

        
    except Exception as e:
        logging.error(f"Error generating preview for {full_name}: {e}")
        image_data=None
    finally:
        # Clean up by deleting the copied presentation
        try:
            drive_service.files().delete(fileId=copied_presentation_id).execute()
            return image_data
        except Exception as e:
            logging.error(f"Error deleting copied presentation: {e}")

# Function to process and send certificates (unchanged)
def process_and_send_certificates(presentation_id, subject, body, row):
    # Initialize Google Drive and Slides services
    drive_service = build('drive', 'v3', credentials=creds)
    slides_service = build('slides', 'v1', credentials=creds)

    full_name = row['Full Name']
    email = row['Email']

    if pd.notna(full_name) and pd.notna(email): 
        email_body = body.replace("{Full_Name}", full_name)

        try:
            # Create a copy of the presentation
            presentation_copy = drive_service.files().copy(
                fileId=presentation_id,
                body={'name': f'{full_name} Presentation'}
            ).execute()
            copied_presentation_id = presentation_copy['id']

            # Replace placeholders in the copied presentation
            slides_service.presentations().batchUpdate(
                presentationId=copied_presentation_id,
                body={
                    'requests': [{
                        'replaceAllText': {
                            'containsText': {
                                'text': '{{Full_Name}}',
                                'matchCase': True
                            },
                            'replaceText': full_name
                        }
                    }]
                }
            ).execute()

            # Export as PDF
            pdf_blob = drive_service.files().export(
                fileId=copied_presentation_id,
                mimeType='application/pdf'
            ).execute()

            # Send email with the attached PDF
            msg = MIMEMultipart()
            msg['From'] = os.getenv("EMAIL_ADDRESS")
            msg['To'] = email
            msg['Subject'] = subject
            msg.attach(MIMEText(email_body, 'html'))

            pdf_attachment = MIMEApplication(pdf_blob, Name=f"{full_name}_Certificate.pdf")
            pdf_attachment['Content-Disposition'] = f'attachment; filename="{full_name}_Certificate.pdf"'
            msg.attach(pdf_attachment)

            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(os.getenv("EMAIL_ADDRESS"), os.getenv("EMAIL_PASSWORD"))
                server.send_message(msg)

            # Delete the copied presentation
            drive_service.files().delete(fileId=copied_presentation_id).execute()
            return f"Certificate sent successfully to {full_name} ({email})"

        except Exception as e:
            logging.error(f"Error processing {full_name} ({email}): {e}")
            return f"Error processing {full_name} ({email}): {e}"
