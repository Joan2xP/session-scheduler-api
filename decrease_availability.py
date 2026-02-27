import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings') 
from exhibitors.models import Participant

count = 0
for p in Participant.objects.all():
    updated = False
    new_avail = None
    if p.availability and isinstance(p.availability, list):
        # Subtract 26 from the current IDs
        new_avail = [sid - 26 if isinstance(sid, int) else sid for sid in p.availability]
        updated = True
        
    new_only = None
    if p.only_session_occurrences and isinstance(p.only_session_occurrences, list):
        new_only = []
        for occ in p.only_session_occurrences:
            if isinstance(occ, dict) and 'sessionId' in occ and isinstance(occ['sessionId'], int):
                new_occ = occ.copy()
                new_occ['sessionId'] -= 26
                new_only.append(new_occ)
                updated = True
            else:
                new_only.append(occ)
                
    new_exclude = None
    if p.exclude_session_occurrences and isinstance(p.exclude_session_occurrences, list):
        new_exclude = []
        for occ in p.exclude_session_occurrences:
            if isinstance(occ, dict) and 'sessionId' in occ and isinstance(occ['sessionId'], int):
                new_occ = occ.copy()
                new_occ['sessionId'] -= 26
                new_exclude.append(new_occ)
                updated = True
            else:
                new_exclude.append(occ)

    new_min = None
    if p.min_sessions_together and isinstance(p.min_sessions_together, dict):
        new_min = p.min_sessions_together.copy()
        if 'sessionId' in new_min and isinstance(new_min['sessionId'], int):
            new_min['sessionId'] -= 26
            updated = True
            
    if updated:
        update_fields = {}
        if new_avail is not None:
            update_fields['availability'] = new_avail
        if new_only is not None:
            update_fields['only_session_occurrences'] = new_only
        if new_exclude is not None:
            update_fields['exclude_session_occurrences'] = new_exclude
        if new_min is not None:
            update_fields['min_sessions_together'] = new_min
            
        Participant.objects.filter(id=p.id).update(**update_fields)
        count += 1

print(f"Bypassed validation and reduced IDs by 26 for {count} participants.")
