import os
import json
import time
import logging
import zipfile
import argparse
from datetime import date, datetime
from dotenv import load_dotenv
from garminconnect import Garmin

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RunningFITFetcher")

# Paths to your existing Garmin Analyzer credentials
GARMIN_ANALYZER_DIR = r"c:\Users\rmelamed\Projects\garmin-analyzer"
ENV_PATH = os.path.join(GARMIN_ANALYZER_DIR, ".env")
TOKEN_STORE = os.path.join(GARMIN_ANALYZER_DIR, ".garmin_tokens")

def get_garmin_client() -> Garmin:
    """
    Initializes and authenticates the Garmin client using the existing credentials
    and tokens from your garmin-analyzer project.
    """
    load_dotenv(ENV_PATH)
    email = os.getenv("GARMIN_USERNAME")
    password = os.getenv("GARMIN_PASS")

    if not email or not password:
        logger.error(f"Could not find GARMIN_USERNAME or GARMIN_PASS in {ENV_PATH}")
        raise ValueError("Missing credentials.")

    try:
        logger.info(f"Connecting to Garmin Connect using shared tokens from {TOKEN_STORE}...")
        client = Garmin(email, password)
        client.login(TOKEN_STORE)
        logger.info("Successfully authenticated.")
        return client
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise Exception(f"Failed to authenticate with Garmin Connect: {e}")

def fetch_running_fits(start_dt: date, end_dt: date, output_dir: str):
    """
    Fetches only 'running' activities between start_dt and end_dt.
    Downloads the FIT files to output_dir, skipping existing ones.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        client = get_garmin_client()
    except Exception as e:
        logger.error(f"Cannot proceed without active Garmin connection: {e}")
        return

    logger.info(f"Scanning history from {start_dt} to {end_dt} for RUNNING activities...")
    
    try:
        activities = client.get_activities_by_date(start_dt.isoformat(), end_dt.isoformat())
    except Exception as e:
        logger.error(f"Failed to fetch activities: {e}")
        return

    running_activities = [
        act for act in activities 
        if act.get("activityType", {}).get("typeKey", "") == "running"
    ]

    logger.info(f"Found {len(activities)} total activities in range, {len(running_activities)} are running.")

    downloaded = 0
    skipped = 0

    for act in running_activities:
        act_id = str(act["activityId"])
        start_time = act.get("startTimeLocal", "unknown time")
        distance = act.get("distance", 0) / 1000.0  # Convert meters to km
        
        filename = os.path.join(output_dir, f"{act_id}.fit")
        
        if os.path.exists(filename):
            logger.debug(f"Skipping {act_id} - already exists locally.")
            skipped += 1
            continue
            
        try:
            logger.info(f"Downloading Run: {act_id} ({start_time}, {distance:.2f} km)...")
            data = client.download_activity(int(act_id), dl_fmt=client.ActivityDownloadFormat.ORIGINAL)
            
            # Save the zip temporarily
            zip_path = os.path.join(output_dir, f"{act_id}.zip")
            with open(zip_path, "wb") as f:
                f.write(data)
                
            # Extract the inner FIT file
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                fit_files_in_zip = [n for n in zip_ref.namelist() if n.lower().endswith('.fit')]
                if fit_files_in_zip:
                    zip_ref.extract(fit_files_in_zip[0], path=output_dir)
                    extracted_path = os.path.join(output_dir, fit_files_in_zip[0])
                    # Rename it to our standard format
                    if os.path.exists(filename):
                        os.remove(filename)
                    os.rename(extracted_path, filename)
            
            # Clean up the zip
            os.remove(zip_path)
            
            downloaded += 1
            time.sleep(2.5)  # Rate limiting
            
        except Exception as e:
            logger.error(f"Failed to download {act_id}: {e}")

    logger.info(f"Fetch Complete: {downloaded} downloaded, {skipped} already present.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Garmin Running FIT files.")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=date.today().isoformat(), help="End date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--out", type=str, default="FIT Files", help="Output directory for FIT files. Defaults to 'FIT Files'.")
    
    args = parser.parse_args()
    
    try:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
        end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    except ValueError:
        logger.error("Invalid date format. Please use YYYY-MM-DD.")
        exit(1)
        
    fetch_running_fits(start_date, end_date, args.out)
