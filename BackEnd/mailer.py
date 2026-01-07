import smtplib
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict

# Configuration file path
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "data", "email_config.json")

def load_email_config():
    """Load email configuration from config file, use defaults if not exists"""
    default_config = {
        "smtp_server": "smtp.126.com",
        "smtp_port": 465,
        "smtp_login": "xinccp@126.com",
        "smtp_password": "ZSrv7U36s3CyxaU2",
        "sender_name": "Cattle Match System"
    }
    
    # Ensure data directory exists
    config_dir = os.path.dirname(CONFIG_FILE)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    
    # If config file doesn't exist, create default config
    if not os.path.exists(CONFIG_FILE):
        save_email_config(default_config)
        return default_config
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # Ensure all required fields exist
            for key in default_config:
                if key not in config:
                    config[key] = default_config[key]
            return config
    except Exception as e:
        print(f"⚠️ Failed to load email config: {e}, using defaults")
        return default_config

def save_email_config(config: dict):
    """Save email configuration to file"""
    try:
        config_dir = os.path.dirname(CONFIG_FILE)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ Failed to save email config: {e}")
        return False

def get_email_config():
    """Get current email configuration"""
    config = load_email_config()
    return {
        "smtp_server": config.get("smtp_server", "smtp.126.com"),
        "smtp_port": config.get("smtp_port", 465),
        "smtp_login": config.get("smtp_login", ""),
        "sender_name": config.get("sender_name", "Cattle Match System"),
        # Password not returned, only return if it's set
        "password_set": bool(config.get("smtp_password", ""))
    }

# Load configuration
_email_config = load_email_config()
SMTP_SERVER = _email_config["smtp_server"]
SMTP_PORT = _email_config["smtp_port"]
SMTP_LOGIN = _email_config["smtp_login"]
SMTP_PASSWORD = _email_config["smtp_password"]
SENDER_EMAIL = SMTP_LOGIN
SENDER_NAME = _email_config["sender_name"]

def reload_email_config():
    """Reload email configuration (call after updating config)"""
    global SMTP_SERVER, SMTP_PORT, SMTP_LOGIN, SMTP_PASSWORD, SENDER_EMAIL, SENDER_NAME
    _email_config = load_email_config()
    SMTP_SERVER = _email_config["smtp_server"]
    SMTP_PORT = _email_config["smtp_port"]
    SMTP_LOGIN = _email_config["smtp_login"]
    SMTP_PASSWORD = _email_config["smtp_password"]
    SENDER_EMAIL = SMTP_LOGIN
    SENDER_NAME = _email_config["sender_name"]

def send_match_email(to_email: str, subject: str, match_details: Dict):
    """
    Send HTML formatted match notification email (adapted for 126 email SSL)
    """
    # 1. Simple validation
    if "@" not in to_email or "." not in to_email:
        print(f"⚠️ Skipped email for non-email contact: {to_email}")
        return

    try:
        # Reload configuration to ensure using latest settings
        config = load_email_config()
        smtp_server = config["smtp_server"]
        smtp_port = config["smtp_port"]
        smtp_login = config["smtp_login"]
        smtp_password = config["smtp_password"]
        sender_name = config["sender_name"]
        sender_email = smtp_login

        # 2. Build email object
        msg = MIMEMultipart()
        msg['From'] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg['To'] = to_email
        msg['Subject'] = f"🔔 {subject}"

        # 3. Build HTML content
        html_content = f"""
<html>
<body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #333; line-height: 1.6;">
<div style="max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 8px; overflow: hidden;">
<div style="background: #c0392b; color: white; padding: 20px; text-align: center;">
<h2 style="margin: 0;">Match Found</h2>
</div>
<div style="padding: 30px;">
<p>Hello,</p>
<p>Great news! The system has identified a potential match for your listing.</p>

<div style="background: #f8f9fa; padding: 15px; border-radius: 6px; margin: 20px 0; border-left: 4px solid #c0392b;">
<h3 style="margin-top: 0; color: #2c3e50;">Match Details</h3>
<ul style="list-style: none; padding: 0;">
            <li><strong>Role:</strong> {match_details.get('role', 'Partner')}</li>
            <li><strong>Race:</strong> {match_details.get('race', 'N/A')}</li>
            <li><strong>Location:</strong> {match_details.get('location', 'N/A')}</li>
            <li><strong>Quantity:</strong> {match_details.get('qty', 'N/A')}</li>
</ul>
</div>

<p style="font-size: 0.9em; color: #666;">
Log in to your dashboard to view contact details.
</p>

<a href="https://bi.cool/full/project/tx7C2rt" style="display: inline-block; background: #2c3e50; color: white; text-decoration: none; padding: 10px 20px; border-radius: 4px; font-weight: bold; margin-top: 10px;">Go to Dashboard</a>
</div>
</div>
</body>
</html>
            """

        msg.attach(MIMEText(html_content, 'html'))

        # 4. Connect to server
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
        
        server.login(smtp_login, smtp_password)

        text = msg.as_string()
        server.sendmail(sender_email, to_email, text)
        server.quit()

        print(f"✅ Email sent successfully to {to_email}")

    except Exception as e:
        print(f"❌ Failed to send email to {to_email}: {e}")

# Local testing
if __name__ == "__main__":
    # Fill in your receiving email here to test
    send_match_email("959489042@qq.com", "Test Subject", {"role": "Tester", "race": "Angus"})

def send_contact_info_email(to_email: str, listing_details: Dict):
    """
    Send unlocked contact information to requester
    """
    subject = "🔓 Unlocked: Contact Details for Your Interest"

    try:
        # Reload configuration to ensure using latest settings
        config = load_email_config()
        smtp_server = config["smtp_server"]
        smtp_port = config["smtp_port"]
        smtp_login = config["smtp_login"]
        smtp_password = config["smtp_password"]
        sender_name = config["sender_name"]
        sender_email = smtp_login

        msg = MIMEMultipart()
        msg['From'] = f"{sender_name} <{sender_email}>"
        msg['To'] = to_email
        msg['Subject'] = subject

        html_content = f"""
<html>
<body style="font-family: Helvetica, Arial, sans-serif; color: #333; line-height: 1.6;">
<div style="max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 8px; overflow: hidden;">
<div style="background: #34495e; color: white; padding: 20px; text-align: center;">
<h2 style="margin: 0;">Contact Details Unlocked</h2>
</div>
<div style="padding: 30px;">
<p>Hello,</p>
<p>You have successfully unlocked the contact information for the following listing:</p>

<div style="background: #f8f9fa; padding: 15px; border-radius: 6px; margin: 20px 0; border-left: 4px solid #34495e;">
<ul style="list-style: none; padding: 0;">
            <li><strong>Listing Type:</strong> {listing_details.get('type')}</li>
            <li><strong>Race:</strong> {listing_details.get('race')}</li>
            <li><strong>Location:</strong> {listing_details.get('location')}</li>
<li style="margin-top: 10px; font-size: 1.1em; color: #c0392b;">
            <strong>📞 Contact: {listing_details.get('contact')}</strong>
</li>
</ul>
</div>

<p style="font-size: 0.9em; color: #666;">
Good luck with your negotiation!
</p>
</div>
</div>
</body>
</html>
            """

        msg.attach(MIMEText(html_content, 'html'))

        # Connect to server
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
        
        server.login(smtp_login, smtp_password)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()
        print(f"✅ Contact info sent to {to_email}")

    except Exception as e:
        print(f"❌ Failed to send contact info: {e}")

def send_verification_code_email(to_email: str, code: str):
    """
    Send two-factor authentication code email
    """
    if "@" not in to_email or "." not in to_email:
        print(f"⚠️ Skipped email for non-email contact: {to_email}")
        return False

    try:
        # Reload configuration to ensure using latest settings
        config = load_email_config()
        smtp_server = config["smtp_server"]
        smtp_port = config["smtp_port"]
        smtp_login = config["smtp_login"]
        smtp_password = config["smtp_password"]
        sender_name = config["sender_name"]
        sender_email = smtp_login

        msg = MIMEMultipart()
        msg['From'] = f"{sender_name} <{sender_email}>"
        msg['To'] = to_email
        msg['Subject'] = "🔐 Two-Factor Authentication Code - Cattle Match System"

        html_content = f"""
<html>
<body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #333; line-height: 1.6;">
<div style="max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 8px; overflow: hidden;">
<div style="background: #2c3e50; color: white; padding: 20px; text-align: center;">
<h2 style="margin: 0;">Two-Factor Authentication</h2>
</div>
<div style="padding: 30px;">
<p>Hello,</p>
<p>You are attempting to perform a sensitive operation. Please use the following verification code:</p>

<div style="background: #f8f9fa; padding: 20px; border-radius: 6px; margin: 20px 0; text-align: center; border: 2px dashed #2c3e50;">
<h1 style="margin: 0; font-size: 2.5rem; color: #2c3e50; letter-spacing: 8px;">{code}</h1>
</div>

<p style="font-size: 0.9em; color: #666;">
This code will expire in 10 minutes. If you did not request this code, please ignore this email.
</p>

<p style="font-size: 0.85em; color: #999; margin-top: 30px;">
Cattle Match System - Secure & Reliable
</p>
</div>
</div>
</body>
</html>
        """

        msg.attach(MIMEText(html_content, 'html'))

        # Connect to server
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
        
        server.login(smtp_login, smtp_password)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()

        print(f"✅ Verification code sent to {to_email}")
        return True

    except Exception as e:
        print(f"❌ Failed to send verification code: {e}")
        return False 