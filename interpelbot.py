import requests
from datetime import datetime
import os
import json

# Dodane: ładowanie zmiennych środowiskowych z pliku .env jeśli istnieje
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def get_data_file_path(mp_id):
    """Get absolute path to the data file for specific MP"""
    # Get the directory where the script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Check if we're running in Docker (data directory mounted)
    docker_data_path = f"/app/data/interpel_{mp_id}.json"
    if os.path.exists(docker_data_path):
        return docker_data_path
    
    # Otherwise use the data subdirectory in the script directory
    data_dir = os.path.join(script_dir, "data")
    return os.path.join(data_dir, f"interpel_{mp_id}.json")

def get_mattermost_webhook_url():
    """Get Mattermost webhook URL from config or environment variable"""
    # Try to get from config first
    config = load_config()
    if config and config.get('mattermost_webhook_url'):
        return config.get('mattermost_webhook_url')
    
    # Fallback to environment variable
    return os.getenv('MATTERMOST_WEBHOOK_URL')

def load_config():
    """Load configuration from JSON file"""
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Błąd podczas wczytywania konfiguracji: {e}")
        return None

def get_mattermost_users_for_interpellation(from_field, config):
    """Get Mattermost users for all MPs who submitted the interpellation"""
    if not from_field or not config:
        return ""
    
    # Split the from_field by comma to get individual MP IDs
    mp_ids = [mp_id.strip() for mp_id in from_field.split(',') if mp_id.strip()]
    
    # Get all Mattermost users for MPs in the config who submitted this interpellation
    all_users = []
    for mp_config in config.get('mps', []):
        mp_id = mp_config.get('id')
        if mp_id and mp_id in mp_ids:
            mattermost_users = mp_config.get('mattermost_users', '')
            if mattermost_users:
                # Split by space and add individual users
                users = [user.strip() for user in mattermost_users.split() if user.strip()]
                all_users.extend(users)
    
    # Remove duplicates while preserving order
    unique_users = []
    for user in all_users:
        if user not in unique_users:
            unique_users.append(user)
    
    return " ".join(unique_users)

def calculate_days_between_dates(date1_str, date2_str):
    """Calculate days between two dates in ISO format"""
    try:
        from datetime import datetime
        
        # Handle different date formats
        def parse_date(date_str):
            # Remove timezone info if present
            date_str = date_str.replace('Z', '').replace('+00:00', '')
            
            # Try different formats
            formats = [
                '%Y-%m-%dT%H:%M:%S',  # 2024-01-23T22:01:02
                '%Y-%m-%d',          # 2023-11-18
                '%Y-%m-%d %H:%M:%S'  # 2024-01-23 22:01:02
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
            
            raise ValueError(f"Nie można sparsować daty: {date_str}")
        
        date1 = parse_date(date1_str)
        date2 = parse_date(date2_str)
        delta = date2 - date1
        return delta.days
        
    except Exception as e:
        print(f"⚠️  Błąd podczas obliczania dni między datami: {e}")
        return None

def get_interpellation_timing_info(replies_data):
    """Get timing information for interpellation and first response"""
    if not replies_data or not isinstance(replies_data, list):
        return None, None, None
    
    # Find the earliest receipt date (when interpellation was submitted)
    receipt_dates = []
    first_response_date = None
    
    for reply in replies_data:
        if isinstance(reply, dict):
            receipt_date = reply.get('receiptDate', '')
            if receipt_date:
                receipt_dates.append(receipt_date)
            
            # Get the earliest lastModified as first response date
            last_modified = reply.get('lastModified', '')
            if last_modified and (first_response_date is None or last_modified < first_response_date):
                first_response_date = last_modified
    
    if not receipt_dates:
        return None, None, None
    
    # Get the earliest receipt date (when interpellation was submitted)
    submission_date = min(receipt_dates)
    
    # Calculate days to first response
    days_to_response = None
    if first_response_date:
        days_to_response = calculate_days_between_dates(submission_date, first_response_date)
    
    return submission_date, first_response_date, days_to_response

def get_interpellation_submission_date_from_api(interpellation_id, interpellation_type, term="10"):
    """Get submission date from API for a specific interpellation"""
    try:
        # Try to get detailed information from API
        if interpellation_type == "INT":
            url = f"https://api.sejm.gov.pl/sejm/term{term}/interpellations/{interpellation_id}"
        else:
            url = f"https://api.sejm.gov.pl/sejm/term{term}/writtenQuestions/{interpellation_id}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        if isinstance(data, dict):
            # Look for submission date in various possible fields
            submission_date = data.get('submissionDate') or data.get('date') or data.get('created') or data.get('receiptDate')
            return submission_date
        
        return None
        
    except Exception as e:
        print(f"⚠️  Błąd podczas pobierania daty złożenia z API: {e}")
        return None

def send_mattermost_notification(message, webhook_url=None):
    """Send notification to Mattermost channel"""
    if not webhook_url:
        webhook_url = get_mattermost_webhook_url()
    
    if not webhook_url:
        print("⚠️  Brak URL webhook Mattermost - pomijam powiadomienie")
        return False
    
    try:
        payload = {
            "text": message,
            "username": "InterpelBot",
            "icon_emoji": ":parliament:"
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        
        print(f"✅ Powiadomienie wysłane do Mattermost")
        return True
        
    except Exception as e:
        print(f"❌ Błąd podczas wysyłania powiadomienia: {e}")
        return False

def send_consolidated_notification(all_new_answers, term):
    """Send separate notifications for each interpellation with new answers"""
    if not all_new_answers:
        return
    
    # Remove duplicates based on interpellation ID and type
    unique_answers = {}
    for answer in all_new_answers:
        key = f"{answer['id']}_{answer['type']}"
        if key not in unique_answers:
            unique_answers[key] = answer
        else:
            # Merge Mattermost users if this is the same interpellation from different MPs
            existing_users = unique_answers[key].get('mattermost_users', '')
            new_users = answer.get('mattermost_users', '')
            if existing_users and new_users:
                # Combine users without duplicates
                all_users = existing_users.split() + new_users.split()
                unique_users = list(dict.fromkeys(all_users))  # Remove duplicates while preserving order
                unique_answers[key]['mattermost_users'] = ' '.join(unique_users)
    
    # Convert back to list
    unique_answers_list = list(unique_answers.values())
    
    print(f"📧 Wysyłam {len(unique_answers_list)} osobnych powiadomień dla każdej interpelacji...")
    
    # Send separate notification for each interpellation
    for answer in unique_answers_list:
        # Prepare individual notification message
        message = f"## 🆕 Nowa odpowiedź na interpelację!\n\n"
        message += f"#### {answer['title']} {answer['type']} ({answer['id']})\n"
        
        # Add information about MPs who submitted the interpellation
        from_field = answer.get('from', '')
        if from_field:
            message += f"**Zapytanie złożył/a/li:** {from_field}\n"
        
        message += f"Odpowiedzi: {answer['previous_replies']} → {answer['current_replies']} (+{answer['new_count']})\n"
        
        # Add information about who provided the answers
        reply_authors = answer.get('reply_authors', [])
        if reply_authors:
            authors_text = ", ".join(reply_authors)
            message += f"**Odpowiada:** {authors_text}\n"
        
        # Add timing information
        submission_date = None
        days_to_response = None
        
        # Try to get timing info from the answer data if available
        if 'submission_date' in answer:
            submission_date = answer['submission_date']
            if 'first_response_date' in answer:
                days_to_response = calculate_days_between_dates(submission_date, answer['first_response_date'])
        
        if submission_date:
            # Format submission date
            try:
                from datetime import datetime
                sub_date = datetime.fromisoformat(submission_date.replace('Z', '+00:00'))
                formatted_submission_date = sub_date.strftime("%d.%m.%Y")
                message += f"**Złożono:** {formatted_submission_date}\n"
            except:
                message += f"**Złożono:** {submission_date}\n"
        
        if days_to_response is not None:
            message += f"**Dni do odpowiedzi:** {days_to_response}\n"
        
        # Add prolongation information if available
        if answer.get('has_prolongation', False):
            message += f"⏰ **Przedłużenie terminu odpowiedzi**\n"
        
        # Extract href from URL object or use URL directly if it's a string
        url_display = answer['url']['href'] if isinstance(answer['url'], dict) and 'href' in answer['url'] else answer['url']
        message += f"{url_display}\n\n--------------------------------\n\n"
        
        # Add Mattermost users for this specific interpellation
        interpellation_users = answer.get('mattermost_users', '')
        if interpellation_users:
            message += f"{interpellation_users}\n"
        
        # Send individual notification
        send_mattermost_notification(message)

def load_previous_results(mp_id):
    """Load previous results from JSON file for specific MP"""
    filename = get_data_file_path(mp_id)
    print(f"🔍 Sprawdzam plik dla posła {mp_id}: {filename}")
    try:
        if os.path.exists(filename):
            print(f"✅ Plik istnieje, wczytuję dane...")
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"📊 Wczytano {len(data)} interpelacji z pliku")
                return data
        else:
            print(f"❌ Plik nie istnieje: {filename}")
        return []
    except Exception as e:
        print(f"⚠️  Błąd podczas wczytywania poprzednich wyników: {e}")
        return []

def compare_and_notify_new_answers(current_results, previous_results, mp_id, term):
    """Compare current and previous results and return new answers (without sending notifications)"""
    if not previous_results:
        print("📝 Pierwsze uruchomienie - brak poprzednich wyników do porównania")
        print("📭 Brak nowych odpowiedzi")
        return []
    
    print(f"🔍 Porównuję z poprzednimi wynikami dla posła {mp_id}...")
    
    # Get Mattermost users from config for this MP
    config = load_config()
    mattermost_users = ""
    if config:
        for mp_config in config.get('mps', []):
            if mp_config.get('id') == mp_id:
                mattermost_users = mp_config.get('mattermost_users', '')
                break
    
    # Create dictionary for quick lookup (use both id and type as key)
    previous_dict = {}
    for item in previous_results:
        if item.get('id'):
            key = f"{item['id']}_{item.get('type', '')}"
            previous_dict[key] = item
    
    new_answers = []
    
    for current_item in current_results:
        current_id = current_item.get('id')
        current_type = current_item.get('type', '')
        if not current_id:
            continue
            
        # Create key using both id and type
        current_key = f"{current_id}_{current_type}"
        previous_item = previous_dict.get(current_key)
        
        if previous_item:
            previous_replies = previous_item.get('replies', 0)
            current_replies = current_item.get('replies', 0)
            
            if current_replies > previous_replies:
                new_count = current_replies - previous_replies
                
                # Check all replies to determine if ALL are prolongations
                # has_prolongation should be True only if ALL replies are prolongations
                # If any reply is not a prolongation, it means there's a real answer
                has_prolongation = False
                new_reply_authors = []
                current_replies_data = current_item.get('replies_data', [])
                if isinstance(current_replies_data, list) and len(current_replies_data) > 0:
                    # Check all replies to see if all are prolongations
                    all_are_prolongations = True
                    has_non_prolongation_reply = False
                    
                    # Check only the newest replies (those beyond the previous count) for authors
                    new_replies = current_replies_data[previous_replies:] if len(current_replies_data) > previous_replies else []
                    for reply in new_replies:
                        if isinstance(reply, dict):
                            # Collect author information from new replies
                            author = reply.get('author', '')
                            if author and author not in new_reply_authors:
                                new_reply_authors.append(author)
                    
                    # Check ALL replies to determine prolongation status
                    for reply in current_replies_data:
                        if isinstance(reply, dict):
                            if reply.get('prolongation') != True:
                                has_non_prolongation_reply = True
                                break
                    
                    # has_prolongation = True only if all replies are prolongations and there's no real answer
                    has_prolongation = not has_non_prolongation_reply and len(current_replies_data) > 0
                
                # Convert MP IDs to names only for interpelations with new answers
                from_field = current_item.get('from', '')
                from_field_names = convert_mp_ids_to_names(from_field, term)
                
                # Get Mattermost users for all MPs who submitted this interpellation
                interpellation_mattermost_users = get_mattermost_users_for_interpellation(from_field, config)
                
                # Get timing information
                replies_data = current_item.get('replies_data', [])
                submission_date = current_item.get('submission_date')
                first_response_date = None
                days_to_response = None
                
                # If not available from object, try to get from API
                if not submission_date:
                    submission_date = get_interpellation_submission_date_from_api(current_id, current_item.get('type'), term)
                
                # If still not available, try to get from replies data
                if not submission_date:
                    submission_date, first_response_date, days_to_response = get_interpellation_timing_info(replies_data)
                else:
                    # Calculate days to first response using submission date
                    for reply in replies_data:
                        if isinstance(reply, dict):
                            last_modified = reply.get('lastModified', '')
                            if last_modified and (first_response_date is None or last_modified < first_response_date):
                                first_response_date = last_modified
                    
                    if first_response_date:
                        days_to_response = calculate_days_between_dates(submission_date, first_response_date)
                
                new_answers.append({
                    'id': current_id,
                    'type': current_item.get('type'),
                    'title': current_item.get('title'),
                    'url': current_item.get('url'),
                    'from': from_field_names,  # Use converted names
                    'previous_replies': previous_replies,
                    'current_replies': current_replies,
                    'new_count': new_count,
                    'has_prolongation': has_prolongation,
                    'reply_authors': new_reply_authors,  # Add author information
                    'mattermost_users': interpellation_mattermost_users,  # Add Mattermost users for this interpellation
                    'submission_date': submission_date,
                    'first_response_date': first_response_date,
                    'days_to_response': days_to_response
                })
        else:
            # New interpellation with answers
            current_replies = current_item.get('replies', 0)
            if current_replies > 0:
                # Check all replies to determine if ALL are prolongations
                # has_prolongation should be True only if ALL replies are prolongations
                # If any reply is not a prolongation, it means there's a real answer
                has_prolongation = False
                reply_authors = []
                current_replies_data = current_item.get('replies_data', [])
                if isinstance(current_replies_data, list):
                    # Check if all replies are prolongations
                    has_non_prolongation_reply = False
                    for reply in current_replies_data:
                        if isinstance(reply, dict):
                            if reply.get('prolongation') != True:
                                has_non_prolongation_reply = True
                            # Collect author information
                            author = reply.get('author', '')
                            if author and author not in reply_authors:
                                reply_authors.append(author)
                    
                    # has_prolongation = True only if all replies are prolongations and there's no real answer
                    has_prolongation = not has_non_prolongation_reply and len(current_replies_data) > 0
                
                # Convert MP IDs to names only for interpelations with new answers
                from_field = current_item.get('from', '')
                from_field_names = convert_mp_ids_to_names(from_field, term)
                
                # Get Mattermost users for all MPs who submitted this interpellation
                interpellation_mattermost_users = get_mattermost_users_for_interpellation(from_field, config)
                
                # Get timing information
                replies_data = current_item.get('replies_data', [])
                submission_date = current_item.get('submission_date')
                first_response_date = None
                days_to_response = None
                
                # If not available from object, try to get from API
                if not submission_date:
                    submission_date = get_interpellation_submission_date_from_api(current_id, current_item.get('type'), term)
                
                # If still not available, try to get from replies data
                if not submission_date:
                    submission_date, first_response_date, days_to_response = get_interpellation_timing_info(replies_data)
                else:
                    # Calculate days to first response using submission date
                    for reply in replies_data:
                        if isinstance(reply, dict):
                            last_modified = reply.get('lastModified', '')
                            if last_modified and (first_response_date is None or last_modified < first_response_date):
                                first_response_date = last_modified
                    
                    if first_response_date:
                        days_to_response = calculate_days_between_dates(submission_date, first_response_date)
                
                new_answers.append({
                    'id': current_id,
                    'type': current_item.get('type'),
                    'title': current_item.get('title'),
                    'url': current_item.get('url'),
                    'from': from_field_names,  # Use converted names
                    'previous_replies': 0,
                    'current_replies': current_replies,
                    'new_count': current_replies,
                    'has_prolongation': has_prolongation,
                    'reply_authors': reply_authors,  # Add author information
                    'mattermost_users': interpellation_mattermost_users,  # Add Mattermost users for this interpellation
                    'submission_date': submission_date,
                    'first_response_date': first_response_date,
                    'days_to_response': days_to_response
                })
    
    # Return new answers if there are any
    if new_answers:
        print(f"🎉 Znaleziono {len(new_answers)} interpelacji z nowymi odpowiedziami!")
        
        # Log IDs of interpelations with new answers
        answer_ids = [answer['id'] for answer in new_answers]
        print(f"📋 ID interpelacji z nowymi odpowiedziami: {', '.join(answer_ids)}")
        
        return new_answers
    else:
        print("📭 Brak nowych odpowiedzi")
        return []

def save_results_to_json(results, mp_id):
    """Save search results to JSON file for specific MP"""
    filename = get_data_file_path(mp_id)
    
    # Ensure the directory exists (for Docker data directory)
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # Count answers
    answered_count = sum(1 for item in results if item.get('replies', 0) > 0)
    total_count = len(results)
    
    # Get current date and time
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"\n" + "="*60)
    print(f"PODSUMOWANIE WYNIKÓW DLA POSŁA {mp_id}")
    print(f"="*60)
    print(f"Data sprawdzenia: {current_datetime}")
    print(f"Wyniki zapisano do pliku: {filename}")
    print(f"Łączna liczba interpelacji: {total_count}")
    print(f"Interpelacje z odpowiedziami: {answered_count}")
    print(f"Interpelacje bez odpowiedzi: {total_count - answered_count}")
    
    if total_count > 0:
        answered_percentage = (answered_count / total_count) * 100
        print(f"Procent interpelacji z odpowiedziami: {answered_percentage:.1f}%")
    
    print(f"="*60)
    return filename





def process_single_mp(mp_id, term):
    """Process interpelations for a single MP and return new answers"""
    print(f"\n{'='*60}")
    print(f"PRZETWARZANIE POSŁA {mp_id}")
    print(f"{'='*60}")
    
    # Load previous results for comparison
    previous_results = load_previous_results(mp_id)
    
    print(f"Pobieranie interpelacji dla posła {mp_id} z API Sejmu...")
    interpellations = fetch_interpellations_from_api(mp_id, term)
    
    if not interpellations:
        print(f"Nie udało się pobrać interpelacji dla posła {mp_id} z API.")
        return []
    
    print(f"Znaleziono {len(interpellations)} interpelacji dla posła {mp_id} w API.")
    
    # Porównaj z poprzednimi wynikami i zwróć nowe odpowiedzi
    new_answers = compare_and_notify_new_answers(interpellations, previous_results, mp_id, term)
    
    # Zapisz wszystkie interpelacje po porównaniu
    save_results_to_json(interpellations, mp_id)
    
    return new_answers

def fetch_mp_data(mp_id, term="10"):
    """Fetch MP data from Sejm API"""
    try:
        url = f"https://api.sejm.gov.pl/sejm/term{term}/MP/{mp_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.205 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.8'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        mp_data = response.json()
        return {
            'id': mp_data.get('id'),
            'name': mp_data.get('firstLastName', ''),
            'club': mp_data.get('club', '')
        }
        
    except Exception as e:
        print(f"⚠️  Błąd podczas pobierania danych posła {mp_id}: {e}")
        return {'id': mp_id, 'name': f'Poseł {mp_id}', 'club': ''}

def convert_mp_ids_to_names(from_field, term="10"):
    """Convert MP IDs to names using Sejm API"""
    if not from_field:
        return ""
    
    # Split by comma and clean up
    mp_ids = [mp_id.strip() for mp_id in from_field.split(',') if mp_id.strip()]
    
    mp_names = []
    for mp_id in mp_ids:
        mp_data = fetch_mp_data(mp_id, term)
        mp_names.append(mp_data['name'])
    
    return ", ".join(mp_names)

def fetch_interpellations_from_api(mp_id, term):
    """Fetch interpellations from Sejm API for the specified MP"""
    try:
        print(f"🔍 Pobieranie interpelacji dla posła ID: {mp_id} z kadencji: {term}")
        
        # Fetch both types of interpellations
        interpellations = []
        
        # Fetch regular interpellations
        int_url = f"https://api.sejm.gov.pl/sejm/term{term}/interpellations?limit=500&sort_by=num&from={mp_id}"
        print(f"📋 Pobieranie interpelacji z: {int_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.205 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.8'
        }
        
        response = requests.get(int_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        int_data = response.json()
        if isinstance(int_data, list):
            for item in int_data:
                processed_item = process_api_item(item, "INT")
                if processed_item:
                    interpellations.append(processed_item)
        
        # Fetch written questions
        zap_url = f"https://api.sejm.gov.pl/sejm/term{term}/writtenQuestions?limit=500&sort_by=num&from={mp_id}"
        print(f"📋 Pobieranie zapytań pisemnych z: {zap_url}")
        
        response = requests.get(zap_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        zap_data = response.json()
        if isinstance(zap_data, list):
            for item in zap_data:
                processed_item = process_api_item(item, "ZAP")
                if processed_item:
                    interpellations.append(processed_item)
        
        print(f"✅ Pobrano {len(interpellations)} interpelacji z API")
        return interpellations
        
    except requests.RequestException as e:
        print(f"❌ Błąd podczas pobierania z API: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"❌ Błąd podczas parsowania JSON z API: {e}")
        return []
    except Exception as e:
        print(f"❌ Nieoczekiwany błąd API: {e}")
        return []

def process_api_item(item, item_type):
    """Process a single API item and extract required fields"""
    try:

        
        # Extract required fields
        links = item.get('links', [])
        url = links[0] if links else ""
        
        interpellation_id = item.get('num', "")
        title = item.get('title', "")
        from_field = item.get('from', "")
        
        # Handle from field - it might be a list or string
        if isinstance(from_field, list):
            from_field = ", ".join(from_field) if from_field else ""
        elif not isinstance(from_field, str):
            from_field = str(from_field) if from_field else ""
        
        # Count replies
        replies = item.get('replies', [])
        replies_count = len(replies) if isinstance(replies, list) else 0
        
        # Filter replies to keep key, prolongation, lastModified, and author information
        filtered_replies = []
        if isinstance(replies, list):
            for reply in replies:
                if isinstance(reply, dict):

                    
                    filtered_reply = {
                        'key': reply.get('key', ''),
                        'prolongation': reply.get('prolongation', False),
                        'lastModified': reply.get('lastModified', ''),
                        'receiptDate': reply.get('receiptDate', ''),  # Add receipt date
                        'author': reply.get('from', '')  # Use 'from' field as author information
                    }
                    filtered_replies.append(filtered_reply)
        
        return {
            'id': str(interpellation_id),
            'type': item_type,
            'title': title,
            'url': url,
            'from': from_field,  # Keep original IDs for now
            'replies': replies_count,
            'replies_data': filtered_replies,
            'submission_date': item.get('submissionDate') or item.get('date') or item.get('created') or item.get('receiptDate')
        }
        
    except Exception as e:
        print(f"  ⚠️  Błąd podczas przetwarzania elementu API: {e}")
        return None

def main():
    """Main function to run the interpellation search for multiple MPs"""
    # Load configuration
    config = load_config()
    if not config:
        print("❌ Nie udało się wczytać konfiguracji.")
        print("📝 Utwórz plik config.json z konfiguracją posłów.")
        return
    
    # Get term from config
    term = config.get('sejm_term', '10')
    mps = config.get('mps', [])
    
    if not mps:
        print("❌ Brak posłów w konfiguracji")
        return
    
    print(f"📋 Znaleziono {len(mps)} posłów w konfiguracji\n")
    
    # Collect all new answers from all MPs first
    all_new_answers = []
    
    # Process each MP and collect new answers
    for mp_config in mps:
        mp_id = mp_config.get('id')
        
        if not mp_id:
            print("⚠️  Pomijam posła bez ID")
            continue
        
        try:
            new_answers = process_single_mp(mp_id, term)
            if new_answers:
                all_new_answers.extend(new_answers)
        except Exception as e:
            print(f"❌ Błąd podczas przetwarzania posła {mp_id}: {e}")
            continue
    
    # Send consolidated notification if there are any new answers
    if all_new_answers:
        send_consolidated_notification(all_new_answers, term)
    
    print(f"\n✅ Zakończono przetwarzanie wszystkich {len(mps)} posłów")

if __name__ == "__main__":
    main()
