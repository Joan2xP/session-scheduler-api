from exhibitors.models import Participant

count = 0
for p in Participant.objects.all():
    updated = False
    if p.availability and isinstance(p.availability, list):
        p.availability = [sid + 26 if isinstance(sid, int) else sid for sid in p.availability]
        updated = True
        
    if p.only_session_occurrences and isinstance(p.only_session_occurrences, list):
        for occ in p.only_session_occurrences:
            if isinstance(occ, dict) and 'sessionId' in occ and isinstance(occ['sessionId'], int):
                occ['sessionId'] += 26
                updated = True
                
    if p.exclude_session_occurrences and isinstance(p.exclude_session_occurrences, list):
        for occ in p.exclude_session_occurrences:
            if isinstance(occ, dict) and 'sessionId' in occ and isinstance(occ['sessionId'], int):
                occ['sessionId'] += 26
                updated = True
                
    if p.min_sessions_together and isinstance(p.min_sessions_together, dict):
        if 'sessionId' in p.min_sessions_together and isinstance(p.min_sessions_together['sessionId'], int):
            p.min_sessions_together['sessionId'] += 26
            updated = True
            
    if updated:
        p.save()
        count += 1

print(f"Successfully updated session IDs for {count} participants.")
