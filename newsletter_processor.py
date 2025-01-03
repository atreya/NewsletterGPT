import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials

load_dotenv()  # Load environment variables
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
import base64
from email.mime.text import MIMEText
import openai
from datetime import datetime

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
NEWSLETTER_SENDERS = [
    'review@firstround.com',
    'dan@tldrnewsletter.com',
    'lenny@substack.com',
    'andrewchen@substack.com'
]

def get_gmail_service():
    """
    Authenticate and return the Gmail API service.

    This function checks for existing credentials stored in 'token.pickle'.
    If not found or if the credentials are invalid/expired, it initiates the OAuth flow to get new credentials.
    The credentials are then saved back to 'token.pickle' for future use.

    Returns:
        googleapiclient.discovery.Resource: Authorized Gmail API service instance.
    """
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # Refresh the credentials if they are expired
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)  # Start OAuth flow to get new credentials
            creds = flow.run_local_server(port=0)
        
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)  # Save the credentials for future use
    
    return build('gmail', 'v1', credentials=creds)  # Build the Gmail service

def get_newsletter_emails(service, sender_email):
    """
    Retrieve unread emails from a specific sender.

    Args:
        service (googleapiclient.discovery.Resource): Authorized Gmail API service instance.
        sender_email (str): Email address of the newsletter sender.

    Returns:
        list: List of message objects containing the unread emails from the specified sender.
    """
    query = f'from:{sender_email} is:unread'  # Query to find unread emails from the sender
    results = service.users().messages().list(userId='me', q=query, maxResults=1).execute()
    messages = results.get('messages', [])  # Get the list of messages
    return messages

def get_email_content(service, msg_id):
    """
    Retrieve the content of an email by its message ID.

    Args:
        service (googleapiclient.discovery.Resource): Authorized Gmail API service instance.
        msg_id (str): ID of the email message.

    Returns:
        str: Decoded email content as a string.
    """
    message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    payload = message['payload']
    
    if 'parts' in payload:
        parts = payload['parts']
        data = parts[0]['body'].get('data', '')  # Get the data from the first part
    else:
        data = payload['body'].get('data', '')  # Get the data from the body
    
    if data:
        text = base64.urlsafe_b64decode(data).decode()  # Decode the base64 encoded data
        return text
    return ''

def summarize_with_gpt(content):
    """
    Summarize the given content using OpenAI's GPT model.

    Args:
        content (str): The content to be summarized.

    Returns:
        str: The summarized content in 2-3 concise bullet points.
    """
    # Truncate content to ~4000 chars to stay within limits
    truncated_content = content[:4000] + "..." if len(content) > 4000 else content
    
    completion = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Summarize the following newsletter content in 2-3 concise bullet points."},
            {"role": "user", "content": truncated_content}
        ]
    )
    return completion.choices[0].message.content  # Return the summarized content

def send_summary_email(service, summaries):
    """
    Send an email containing the summarized newsletters.

    Args:
        service (googleapiclient.discovery.Resource): Authorized Gmail API service instance.
        summaries (dict): Dictionary containing summaries of newsletters keyed by sender email.

    Returns:
        None
    """
    date_str = datetime.now().strftime('%Y-%m-%d')  # Get the current date
    email_content = f"Newsletter Summaries for {date_str}\n\n"
    
    for sender, summary in summaries.items():
        email_content += f"\nFrom {sender}:\n{summary}\n"  # Append each summary to the email content
    
    message = MIMEText(email_content)
    message['to'] = 'atreya@gmail.com'  # Your verified email
    message['subject'] = f'Newsletter Summaries - {date_str}'
    
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')  # Encode the message
    service.users().messages().send(userId='me', body={'raw': raw_message}).execute()  # Send the email

def archive_email(service, msg_id):
    """
    Archive an email by removing 'UNREAD' and 'INBOX' labels.

    Args:
        service (googleapiclient.discovery.Resource): Authorized Gmail API service instance.
        msg_id (str): ID of the email message to be archived.

    Returns:
        None
    """
    service.users().messages().modify(
        userId='me',
        id=msg_id,
        body={'removeLabelIds': ['UNREAD', 'INBOX']}  # Remove the 'UNREAD' and 'INBOX' labels
    ).execute()

def main():
    """
    Main function to process newsletters.

    This function initializes the Gmail service, retrieves unread newsletters from specified senders,
    summarizes their content using GPT, and sends a summary email. It also archives the processed emails.

    Returns:
        None
    """
    print("Starting newsletter processing...")
    
    # Get OpenAI API key from .env
    openai.api_key = os.getenv('OPENAI_API_KEY')
    
    print("Setting up Gmail service...")
    # Initialize Gmail service
    service = get_gmail_service()
    print("Gmail service initialized")
    
    summaries = {}
    
    # Process each newsletter
    for sender in NEWSLETTER_SENDERS:
        print(f"Checking emails from: {sender}")
        messages = get_newsletter_emails(service, sender)
        print(f"Found {len(messages)} unread messages")
        
        if messages:
            combined_content = ""
            for message in messages:
                content = get_email_content(service, message['id'])
                combined_content += content + "\n\n"  # Combine the content of all messages
                archive_email(service, message['id'])  # Archive the processed email
            
            if combined_content:
                summary = summarize_with_gpt(combined_content)  # Summarize the combined content
                summaries[sender] = summary
    
    # Send combined summary if we have any summaries
    if summaries:
        send_summary_email(service, summaries)

if __name__ == '__main__':
    main()
