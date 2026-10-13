/*
 * Forest AI — Latvian UI layer (display only).
 *
 * Loaded ONLY when the instance runs with UI_LANGUAGE=lv (api.py injects it into
 * index.html). Instances without that setting never load this file, so their UI
 * is byte-for-byte unchanged.
 *
 * How it works: index.html builds its UI from hardcoded RU/EN strings. This file
 * translates them on screen without touching the application logic:
 *   - visible text nodes and placeholder/title/aria-label attributes, also in
 *     content rendered later (MutationObserver);
 *   - alert / confirm / prompt messages;
 *   - Chart.js labels;
 *   - default date formatting (toLocaleString without a locale -> lv-LV).
 *
 * Rules:
 *   - Only EXACT known UI strings and explicit patterns are translated. Anything
 *     unknown (sector names, people, AI output, notes typed by users) is left as is.
 *   - Form fields the user types into, and map attribution, are never touched.
 *   - Data in the database is never changed; this is presentation only.
 *
 * To add a string: put the exact on-screen text (whitespace collapsed) into EXACT.
 */
(function () {
  'use strict';

  var EXACT = {
    // ── Navigation / layout ───────────────────────────────────────────────
    'Overview': 'Pārskats', 'Objects': 'Objekti', 'Sectors': 'Sektori', 'Map': 'Karte',
    'Risks': 'Riski', 'GPS Sessions': 'GPS sesijas', 'Truck Reports': 'Kokvedēju atskaites',
    'Timber': 'Kokmateriāli', 'Photos': 'Foto', 'AI Inspector': 'AI inspektors',
    'Satellite': 'Satelīts', 'Integrations': 'Integrācijas', 'Monitor': 'Monitorings',
    'MONITOR': 'MONITORINGS', 'Operations': 'Operācijas', 'OPERATIONS': 'OPERĀCIJAS',
    'Admin': 'Administrēšana', 'ADMIN': 'ADMINISTRĒŠANA', 'Refresh': 'Atjaunot',
    '↻ Refresh': '↻ Atjaunot', 'Sector detail': 'Sektora detaļas', 'Sector Detail': 'Sektora detaļas',
    '← Back': '← Atpakaļ', '← Back to Risks': '← Atpakaļ uz riskiem', '← back to overview': '← atpakaļ uz pārskatu',
    '← back to sectors': '← atpakaļ uz sektoriem', '→ View all in Risks': '→ Skatīt visus riskos',
    '→ View all in AI Inspector': '→ Skatīt visus AI inspektorā', 'View sector →': 'Skatīt sektoru →',
    'details →': 'detaļas →', 'Loading': 'Ielādē', 'Loading...': 'Ielādē...', 'Loading map': 'Ielādē karti',
    'Loading map...': 'Ielādē karti...', 'Escape': 'Aizvērt', 'Close': 'Aizvērt',

    // ── Overview KPIs (RU) ───────────────────────────────────────────────
    'Риск по инцидентам': 'Risks pēc incidentiem', '⚠ Риск по инцидентам': '⚠ Risks pēc incidentiem',
    'Расчётный риск по операции': 'Aprēķinātais operācijas risks', '⚠ Расчётный риск по операции': '⚠ Aprēķinātais operācijas risks',
    'Секторы': 'Sektori', 'Активные риски': 'Aktīvie riski', 'GPS сессии': 'GPS sesijas',
    'Объём m³': 'Apjoms m³', 'Объём': 'Apjoms', 'Активные операции': 'Aktīvās operācijas',
    'Чек-ины сегодня': 'Reģistrēšanās šodien', 'за сегодня': 'šodien', 'Непроверено': 'Nepārbaudīts',
    'требует проверки': 'jāpārbauda', 'требуют внимания': 'prasa uzmanību', 'секторов в работе': 'sektori darbā',
    'Критические': 'Kritiski', 'критических': 'kritiski', 'рейсов': 'reisi', 'фото': 'foto', 'Фото': 'Foto',
    'Сектор': 'Sektors', 'Подрядчик': 'Darbuzņēmējs', 'Статус': 'Statuss', 'Финансовый риск': 'Finanšu risks',
    'Высокий риск': 'Augsts risks', 'Рекомендация': 'Ieteikums', 'нет рисков': 'nav risku',
    'Риск не указан': 'Risks nav norādīts', 'из 100': 'no 100', 'точек': 'punkti',
    'Основано на AI-анализе конкретных зарегистрированных инцидентов':
      'Balstīts uz konkrētu reģistrētu incidentu AI analīzi',
    'Базовая формула риска по всем секторам, включая те, где ещё не зарегистрировано инцидентов':
      'Bāzes riska formula visiem sektoriem, arī tiem, kuros vēl nav reģistrētu incidentu',
    'отдельно от операционного риска сектора': 'atsevišķi no sektora operacionālā riska',

    // ── Overview / charts / tables (EN) ──────────────────────────────────
    'Risks by sector': 'Riski pa sektoriem', 'RISKS BY SECTOR': 'RISKI PA SEKTORIEM',
    'Timber volume m³': 'Kokmateriālu apjoms m³', 'TIMBER VOLUME M³': 'KOKMATERIĀLU APJOMS M³',
    'Active risks': 'Aktīvie riski', 'ACTIVE RISKS': 'AKTĪVIE RISKI', 'SECTORS': 'SEKTORI',
    'Sector': 'Sektors', 'Sector:': 'Sektors:', 'Level': 'Līmenis', 'Reason': 'Iemesls', 'Risk': 'Risks',
    'Contractor': 'Darbuzņēmējs', 'Status': 'Statuss', 'Status:': 'Statuss:', 'Name': 'Nosaukums',
    'Type': 'Tips', 'Date': 'Datums', 'Time': 'Laiks', 'Period': 'Periods', 'Note': 'Piezīme',
    'Comment': 'Komentārs', 'Comments': 'Komentāri', 'Code': 'Kods', 'Area': 'Platība', 'Volume': 'Apjoms',
    'Volume m³': 'Apjoms m³', 'Employee': 'Darbinieks', 'Worker:': 'Darbinieks:', 'Workers': 'Darbinieki',
    'Driver': 'Vadītājs', 'Phone': 'Tālrunis', 'Role': 'Loma', 'Site': 'Objekts', 'Object': 'Objekts',
    'Entity': 'Vienība', 'Distance m': 'Attālums m', 'Started': 'Sākts', 'Finish': 'Beigas',
    'Check-in': 'Reģistrēšanās', 'Truck': 'Kokvedējs', 'Trucks': 'Kokvedēji', 'Vehicles': 'Transportlīdzekļi',
    'Equipment': 'Tehnika', 'Machines': 'Mašīnas', 'Fleet': 'Autoparks', 'Incidents': 'Incidenti',
    'Recommendations': 'Ieteikumi', 'Recommended': 'Ieteicams', 'Exposure': 'Finanšu ietekme',
    'All': 'Visi', 'All risks': 'Visi riski', 'All sectors': 'Visi sektori', 'All objects': 'Visi objekti',
    'Click sector to open details': 'Noklikšķiniet uz sektora, lai atvērtu detaļas',
    'Search sector...': 'Meklēt sektoru...', 'Search sector': 'Meklēt sektoru',
    'High risk': 'Augsts risks', 'Medium risk': 'Vidējs risks', 'Low risk': 'Zems risks',
    'MEDIUM RISK': 'VIDĒJS RISKS', 'HIGH RISK': 'AUGSTS RISKS', 'LOW RISK': 'ZEMS RISKS',
    'Risk Score': 'Riska vērtējums', 'RISK SCORE': 'RISKA VĒRTĒJUMS', 'Avg risk score': 'Vid. riska vērtējums',
    'at risk': 'apdraudēts', 'Audit': 'Audits', 'Available': 'Pieejams', 'Active': 'Aktīvs',
    'Approved': 'Apstiprināts', 'Planned': 'Plānots', 'Offline': 'Bezsaistē', 'Demo': 'Demo',
    'Error': 'Kļūda', 'Failed': 'Neizdevās', 'Saved': 'Saglabāts', 'Saving': 'Saglabā', 'Saving...': 'Saglabā...',
    'Unknown error': 'Nezināma kļūda', 'null': '—', 'undefined': '—',

    // ── Statuses / levels / codes (shown as badges) ──────────────────────
    'HIGH': 'AUGSTS', 'MEDIUM': 'VIDĒJS', 'LOW': 'ZEMS', 'CRITICAL': 'KRITISKS',
    'OPEN': 'ATVĒRTS', 'RESOLVED': 'ATRISINĀTS', 'CLOSED': 'SLĒGTS', 'ACTIVE': 'AKTĪVS',
    'PLANNED': 'PLĀNOTS', 'APPROVED': 'APSTIPRINĀTS', 'PENDING': 'GAIDA', 'DONE': 'PABEIGTS',
    'DRAFT': 'MELNRAKSTS', 'CONFIRMED': 'APSTIPRINĀTS', 'REJECTED': 'NORAIDĪTS', 'RESHOOT': 'JĀFOTOGRAFĒ ATKĀRTOTI',
    'DISMISSED': 'NORAIDĪTS', 'NOTIFIED': 'PAZIŅOTS', 'WORKER_REPLIED': 'DARBINIEKS ATBILDĒJA',
    'TELEGRAM_SENT': 'NOSŪTĪTS TELEGRAM', 'DETECTED': 'KONSTATĒTS', 'UNCONFIRMED': 'NEAPSTIPRINĀTS',
    'UNREVIEWED': 'NAV PĀRSKATĪTS', 'WITHDRAWN': 'ATSAUKTS', 'UNDONE': 'ATCELTS', 'KEEP_OPEN': 'ATSTĀT ATVĒRTU',
    'CLOSE': 'SLĒGT', 'CONNECTED': 'PIESLĒGTS', 'NOT_CONNECTED': 'NAV PIESLĒGTS', 'OFFLINE': 'BEZSAISTĒ',
    'SYNCING': 'SINHRONIZĒ', 'RUNNING': 'DARBOJAS', 'SUCCESS': 'VEIKSMĪGI', 'FAILED': 'NEIZDEVĀS',
    'ERROR': 'KĻŪDA', 'VALID': 'DERĪGS', 'RECEIVED': 'SAŅEMTS', 'PROCESSED': 'APSTRĀDĀTS', 'IDLE': 'DĪKSTĀVĒ',
    'FULFILLED': 'IZPILDĪTS', 'CREATED': 'IZVEIDOTS', 'MISSING_VOLUME': 'TRŪKST APJOMA',
    'OVER_VOLUME': 'PĀRSNIEGTS APJOMS', 'EQUIPMENT_BREAKDOWN': 'TEHNIKAS BOJĀJUMS', 'EMPLOYEE': 'DARBINIEKS',
    'VEHICLE': 'TRANSPORTLĪDZEKLIS', 'EQUIPMENT': 'TEHNIKA', 'SECTOR_EXIT': 'IZIEŠANA NO SEKTORA',
    'EMERGENCY': 'TRAUKSME', 'DISPATCHER_MESSAGE': 'DISPEČERA ZIŅA', 'AI_RECOMMENDATION_GENERATED': 'AI IETEIKUMS IZVEIDOTS',
    'Not configured': 'Nav konfigurēts', 'no credentials': 'nav piekļuves datu',
    // risk event codes (risk detail timeline)
    'AI_ANALYSIS_FAILED': 'AI analīze neizdevās',
    'AI_ANALYSIS_REQUESTED': 'Pieprasīta AI analīze',
    'AI_RECOMMENDATION_REPLACED': 'AI ieteikums aizstāts',
    'BOUNDARY_VIEW_REQUESTED': 'Pieprasīts robežas skats',
    'CONCLUSION_ACCEPTED': 'Slēdziens pieņemts',
    'CONCLUSION_AI_CALL': 'Slēdziena AI pieprasījums',
    'CONCLUSION_DECISION_UNDONE': 'Slēdziena lēmums atcelts',
    'CONCLUSION_DRAFTED': 'Slēdziena melnraksts izveidots',
    'CONCLUSION_INTERIM': 'Starpslēdziens',
    'CONFIRMED_RETURN': 'Atgriešanās apstiprināta',
    'CONTACT_SERVICE_REQUESTED': 'Pieprasīts serviss',
    'DIAGNOSTICS_ANSWER': 'Diagnostikas atbilde',
    'DIAGNOSTICS_STARTED': 'Diagnostika sākta',
    'DISPATCHER_ALERTED': 'Dispečers informēts',
    'DISPATCHER_ALERT_FAILED': 'Dispečera paziņojums neizdevās',
    'DISPATCHER_NOT_CONFIGURED': 'Dispečers nav iestatīts',
    'EMERGENCY_ESCALATED_FROM_SECTOR_EXIT': 'Iziešana no sektora eskalēta uz trauksmi',
    'EXPLAIN_REQUESTED': 'Pieprasīts paskaidrojums',
    'FIELD_PHOTO_REQUESTED': 'Pieprasīts foto no lauka',
    'FIELD_VERIFICATION_REQUESTED': 'Pieprasīta pārbaude dabā',
    'INVESTIGATION_STARTED': 'Izmeklēšana sākta',
    'LEAVING_ZONE': 'Atstāj zonu',
    'PHOTO_RECEIVED': 'Foto saņemts',
    'REOPENED': 'Atkārtoti atvērts',
    'REPAIR_CHOICE_DISPATCHER_CONSULT': 'Remonts: konsultācija ar dispečeru',
    'REPAIR_CHOICE_SELF': 'Remonts: saviem spēkiem',
    'REPAIR_CHOICE_SERVICE': 'Remonts: serviss',
    'REPAIR_MENU_OPENED': 'Atvērta remonta izvēlne',
    'REPORT_REQUESTED': 'Pieprasīta atskaite',
    'RETURNED_TO_SECTOR': 'Atgriezies sektorā',
    'RETURNING': 'Atgriežas',
    'SAFE': 'Drošībā',
    'SATELLITE_VIEW_REQUESTED': 'Pieprasīts satelītskats',
    'SOS_REPEATED': 'SOS atkārtots',
    'STILL_OUTSIDE': 'Joprojām ārpus sektora',
    'TELEGRAM_SEND_FAILED': 'Telegram nosūtīšana neizdevās',
    'WORK_STOPPED': 'Darbs apturēts',
    'CHANGE_REVIEWED': 'Izmaiņa pārskatīta',
    'CHANGE_REVIEW_UNDONE': 'Izmaiņas pārskatīšana atcelta',
    'system': 'sistēma',
    'dispatcher': 'dispečers',
    'worker': 'darbinieks',
    'YES': 'JĀ', 'NO': 'NĒ', '✓ Approved': '✓ Apstiprināts', '✗ Rejected': '✗ Noraidīts',
    '1. GPS Check-in required before work': '1. Pirms darba obligāta GPS reģistrēšanās',
    '2. Minimum 1 site photo per session': '2. Vismaz 1 objekta foto katrā sesijā',
    '3. Timber movement logged same day': '3. Kokmateriālu pārvietošana reģistrējama tajā pašā dienā',
    '4. Fuel logged after each refuel': '4. Degviela reģistrējama pēc katras uzpildes',
    '5. Session must be closed on finish': '5. Pēc darba sesija jāaizver',

    // ── Sector detail ────────────────────────────────────────────────────
    'Sector info': 'Sektora informācija', 'Sector Summary': 'Sektora kopsavilkums', 'Sector map': 'Sektora karte',
    'Sector risk analysis': 'Sektora riska analīze', 'Sector ID': 'Sektora ID', 'Boundary': 'Robeža',
    'boundary': 'robeža', '✓ defined': '✓ noteikta', 'not set': 'nav noteikta', 'Center Lat': 'Centra platums',
    'Center Lon': 'Centra garums', 'Approved Volume': 'Apstiprinātais apjoms', 'Approved volume': 'Apstiprinātais apjoms',
    'Tree Species': 'Koku sugas', 'Tree Species & Forest Info': 'Koku sugas un meža informācija',
    'Cut Plan Notes': 'Ciršanas plāna piezīmes', 'General Notes': 'Vispārīgās piezīmes', 'ha area': 'ha platība',
    'ha total': 'ha kopā', 'Total area': 'Kopējā platība', 'Boundary Coordinates': 'Robežu koordinātas',
    'Boundary Plan': 'Robežu plāns', 'Boundary plan': 'Robežu plāns', 'Sector location on plan': 'Sektora atrašanās vieta plānā',
    '🌲 Forest': '🌲 Mežs', '👷 People': '👷 Cilvēki', '🚛 Vehicles': '🚛 Transportlīdzekļi', '🗺 Map': '🗺 Karte',
    '🗺 Map Only': '🗺 Tikai karte', '🛰 Satellite': '🛰 Satelīts', '💬 Chat': '💬 Tērzēšana', '📅 История': '📅 Vēsture',
    '📷 Фото': '📷 Foto', '⚠ Work Rules': '⚠ Darba noteikumi', '⚠ Manual': '⚠ Manuāli',
    'Add Worker': 'Pievienot darbinieku', 'Add Vehicle': 'Pievienot transportlīdzekli', 'Add Snapshot': 'Pievienot uzņēmumu',
    '+ Add': '+ Pievienot', '+ Добавить': '+ Pievienot', 'Добавить': 'Pievienot', '+ New Object': '+ Jauns objekts',
    '+ New Sector': '+ Jauns sektors', 'New Object': 'Jauns objekts', 'New Sector': 'Jauns sektors',
    'Create Sector': 'Izveidot sektoru', 'Save': 'Saglabāt', '✓ Save': '✓ Saglabāt', 'Cancel': 'Atcelt',
    'Сохранить': 'Saglabāt', 'Отправить': 'Nosūtīt', 'Analyze': 'Analizēt', '🔍 Analyze': '🔍 Analizēt',
    '🔍 Analyze All Sectors': '🔍 Analizēt visus sektorus', '↓ PDF': '↓ PDF', '↓ PDF Report': '↓ PDF atskaite',
    'Photo gallery': 'Foto galerija', 'no photos': 'nav foto', 'no comments': 'nav komentāru',
    'no vehicles assigned': 'nav piesaistītu transportlīdzekļu', 'no records': 'nav ierakstu', 'no reports': 'nav atskaišu',
    'no scan': 'nav skenējuma', 'no image yet': 'attēla vēl nav', 'no risks': 'nav risku',
    'no risks for this sector': 'šim sektoram nav risku', 'no sectors': 'nav sektoru', 'no sectors yet': 'sektoru vēl nav',
    'no objects yet': 'objektu vēl nav', 'no incidents': 'nav incidentu', 'No events': 'Nav notikumu',
    'No changes': 'Nav izmaiņu', 'No GPS data': 'Nav GPS datu', 'No GPS check-ins recorded': 'GPS reģistrēšanās nav fiksēta',
    'No GPS or boundary data available yet': 'GPS vai robežu dati vēl nav pieejami',
    'Add sector boundaries or GPS check-ins': 'Pievienojiet sektora robežas vai GPS reģistrēšanos',
    'No issues detected': 'Problēmas nav konstatētas', 'No financial risk data': 'Nav finanšu riska datu',
    'No fuel logs yet': 'Degvielas ierakstu vēl nav', 'No truck reports for timber movements': 'Kokmateriālu pārvietošanai nav kokvedēju atskaišu',
    'Request truck delivery reports from contractor': 'Pieprasīt darbuzņēmējam kokvedēju piegādes atskaites',
    'Reconcile timber volumes with contractor reports': 'Salīdzināt kokmateriālu apjomus ar darbuzņēmēja atskaitēm',
    'Conduct immediate audit of sector operations': 'Nekavējoties veikt sektora operāciju auditu',
    'Ensure workers use GPS check-in on site entry': 'Nodrošināt, ka darbinieki reģistrējas ar GPS, ierodoties objektā',
    'Continue routine monitoring': 'Turpināt ierasto monitoringu', 'Baseline monitoring': 'Bāzes monitorings',
    'outside approved': 'ārpus apstiprinātā', 'outside approved zone': 'ārpus apstiprinātās zonas',
    'polygon boundary': 'poligona robeža', 'sector(s) shown': 'sektori parādīti', 'optional note': 'neobligāta piezīme',
    'set by reviewer': 'norādījis pārbaudītājs', 'timber volume mismatch': 'kokmateriālu apjoma neatbilstība',
    'truck report mismatch': 'kokvedēja atskaites neatbilstība',
    'timber movement(s) with missing volume': 'kokmateriālu pārvietošana(-s) bez apjoma',
    'GPS check-in(s) rejected': 'GPS reģistrēšanās noraidīta', 'HIGH risk(s) registered': 'reģistrēti AUGSTI riski',
    'Remove this snapshot?': 'Dzēst šo uzņēmumu?', 'Remove this vehicle?': 'Dzēst šo transportlīdzekli?',
    'Remove this worker?': 'Dzēst šo darbinieku?',
    'Написать работнику...': 'Uzrakstīt darbiniekam...', 'Написать работнику': 'Uzrakstīt darbiniekam',
    '✓ Отправлено': '✓ Nosūtīts', '✓✓ Отвечено': '✓✓ Atbildēts', '⚠ Сетевая ошибка': '⚠ Tīkla kļūda',
    'Coordinates': 'Koordinātas', 'Координаты': 'Koordinātas', 'Площадь': 'Platība', 'Без объекта': 'Bez objekta',
    'Риски снимка': 'Uzņēmuma riski', 'Риски на момент снимка': 'Riski uzņēmuma brīdī',
    'риски для этой даты не отмечены': 'šim datumam riski nav atzīmēti',
    'выезжала за границу сектора': 'izbrauca ārpus sektora robežas', '⚠ Машина': '⚠ Mašīna',

    // ── Form placeholders ────────────────────────────────────────────────
    'Full name': 'Vārds, uzvārds', 'Role (e.g. Logger)': 'Loma (piem., mežizstrādātājs)', 'ID / Personal code': 'ID / personas kods',
    'Telegram user ID': 'Telegram lietotāja ID', 'Driver Telegram ID': 'Vadītāja Telegram ID', 'Plate (e.g. AB-1234)': 'Numurzīme (piem., AB-1234)',
    'Type (Truck/Harvester)': 'Tips (kokvedējs/harvesters)', 'Tank L (e.g. 200)': 'Bāka L (piem., 200)',
    'Active Logging': 'Aktīva mežizstrāde', 'Baltic Forest Ltd': 'Darbuzņēmēja nosaukums',
    'e.g. Pine (Pinus sylvestris) — 60%': 'piem., priede (Pinus sylvestris) — 60%',
    'Approved logging zone, restrictions, seasonal limits...': 'Apstiprinātā ciršanas zona, ierobežojumi, sezonālie ierobežojumi...',
    'Road access, special conditions, audit notes...': 'Piekļuve ar ceļu, īpaši nosacījumi, audita piezīmes...',
    'Zoom in': 'Tuvināt', 'Zoom out': 'Tālināt',

    // ── Risk detail / AI ─────────────────────────────────────────────────
    '🤖 AI Recommendation': '🤖 AI ieteikums', 'AI Recommendation': 'AI ieteikums', '✓ Approve & Send': '✓ Apstiprināt un nosūtīt',
    'Estimated Financial Exposure': 'Prognozētie finanšu zaudējumi', 'Financial Risk Breakdown': 'Finanšu riska sadalījums',
    'Risk & Financial Exposure': 'Risks un finanšu ietekme', 'Send this message to the worker via Telegram?': 'Nosūtīt šo ziņu darbiniekam caur Telegram?',
    'Отправить это сообщение работнику?': 'Nosūtīt šo ziņu darbiniekam?', '🤖 AI Анализ': '🤖 AI analīze',
    '🤖 AI Анализ (все секторы)': '🤖 AI analīze (visi sektori)', 'Анализ секторов': 'Sektoru analīze',
    'агрегированная оценка по всем': 'apkopots novērtējums visiem', 'секторам': 'sektoriem',

    // ── GPS / timber / trucks ────────────────────────────────────────────
    'GPS sessions': 'GPS sesijas', 'Timber Movements': 'Kokmateriālu pārvietošana', 'Timber movements': 'Kokmateriālu pārvietošana',
    'Truck reports': 'Kokvedēju atskaites', 'Planned m³': 'Plānots m³', 'Actual m³': 'Faktiski m³', 'Diff m³': 'Starpība m³',
    'Discrepancy': 'Neatbilstība', 'KM driven': 'Nobraukti km', 'Fuel added L': 'Uzpildīta degviela L', 'Calc L': 'Aprēķināts L',
    'Fuel %': 'Degviela %', 'Brand': 'Marka', 'Model': 'Modelis', 'Color': 'Krāsa', 'Green': 'Zaļa', 'Yellow': 'Dzeltena',
    'Orange': 'Oranža', 'Red': 'Sarkana', 'Blue': 'Zila',

    // ── Satellite ────────────────────────────────────────────────────────
    'Satellite Monitor': 'Satelītu monitorings', 'Satellite Intelligence': 'Satelītu analīze',
    'Satellite Intelligence Engine': 'Satelītu analīzes modulis', 'Satellite Score': 'Satelītu vērtējums',
    'Satellite Risk Score': 'Satelītu riska vērtējums', 'Recommended Tier': 'Ieteicamais līmenis', 'Tier': 'Līmenis',
    'Band': 'Diapazons', 'True Color': 'Dabiskās krāsas', 'Timeline': 'Laika skala', 'Object satellite': 'Objekta satelītattēls',
    'AI decides where expensive imagery is actually necessary': 'AI nosaka, kur dārgi satelītattēli tiešām ir nepieciešami',
    'No satellite activity on record yet.': 'Satelītu aktivitāte vēl nav reģistrēta.',
    '📤 Upload sector satellite': '📤 Augšupielādēt sektora satelītattēlu', 'Sentinel-2 снимок': 'Sentinel-2 attēls',
    'Загрузка Sentinel-2': 'Ielādē Sentinel-2', 'Загрузка снимка Sentinel-2': 'Ielādē Sentinel-2 attēlu',
    'Запрос к Copernicus API': 'Pieprasījums Copernicus API', 'Нажми Загрузить': 'Nospiediet „Ielādēt”',
    '↻ Загрузить': '↻ Ielādēt', '✓ Загружено': '✓ Ielādēts', '⚠ Ошибка загрузки': '⚠ Ielādes kļūda',
    'Дата от': 'Datums no', 'Дата до': 'Datums līdz', 'Дней с посл. снимка': 'Dienas kopš pēd. attēla',
    'Разрешение': 'Izšķirtspēja', '10м': '10 m', '~5 дней': '~5 dienas', 'Обновление': 'Atjaunināšana', 'Обновлено': 'Atjaunināts',
    '🗺 Интерактивная карта': '🗺 Interaktīvā karte', '🗺 Интерактивная карта — выбери сектор': '🗺 Interaktīvā karte — izvēlieties sektoru',
    '— выбери сектор —': '— izvēlieties sektoru —', 'выбери сектор': 'izvēlieties sektoru', 'снимок →': 'attēls →',
    'Нет данных спутникового мониторинга для этого сектора': 'Šim sektoram nav satelītu monitoringa datu',
    'Нет событий в истории мониторинга': 'Monitoringa vēsturē nav notikumu',
    'Ошибка. Попробуй другой диапазон дат или сектор': 'Kļūda. Mēģiniet citu datumu diapazonu vai sektoru',
    'Проверь подключение сервера к интернету': 'Pārbaudiet servera interneta savienojumu',
    'score 51–75': 'vērtējums 51–75', 'score > 75': 'vērtējums > 75',

    // ── Integrations ─────────────────────────────────────────────────────
    'Integration': 'Integrācija', 'Connect': 'Pieslēgt', 'Disconnect': 'Atslēgt', 'Configure': 'Konfigurēt',
    'Credentials': 'Piekļuves dati', 'Test Connection': 'Pārbaudīt savienojumu', 'Sync Now': 'Sinhronizēt tagad',
    'Sync status': 'Sinhronizācijas statuss', 'Sync frequency': 'Sinhronizācijas biežums', 'Sync log': 'Sinhronizācijas žurnāls',
    'Last sync': 'Pēdējā sinhronizācija', 'Last success': 'Pēdējā veiksmīgā', 'Records received': 'Saņemtie ieraksti',
    'Recent log messages': 'Pēdējie žurnāla ieraksti', 'Recent normalized records': 'Pēdējie normalizētie ieraksti',
    'Received': 'Saņemts', 'External ID': 'Ārējais ID', 'Validation': 'Validācija', 'Trigger': 'Palaidējs',
    'Fetched': 'Iegūts', 'Dedup': 'Dublikāti', 'View Logs': 'Skatīt žurnālu', 'Weighbridge': 'Svari',
    'Telegram Bot': 'Telegram bots', 'Telegram · worker': 'Telegram · darbinieks', 'Client ERP system': 'Klienta ERP sistēma',
    'Corporate GIS system': 'Uzņēmuma ĢIS sistēma', 'Weighbridge / scale system': 'Svaru sistēma',
    'Timber accounting / e-waybill system': 'Kokmateriālu uzskaites / e-pavadzīmju sistēma',
    'GeoJSON / KML / GPX / Shapefile import': 'GeoJSON / KML / GPX / Shapefile imports',
    'Fleet GPS (Demo)': 'Autoparka GPS (demo)', 'Weighbridge (Demo)': 'Svari (demo)', 'Sentinel (Demo)': 'Sentinel (demo)',
    'Demo mode available — no real credentials required.': 'Pieejams demo režīms — reāli piekļuves dati nav nepieciešami.',
    'No adapter implemented yet — planned integration.': 'Adapteris vēl nav izveidots — plānota integrācija.',
    'Do not mark Connected until the actual vendor/API is confirmed.': 'Neatzīmēt kā pieslēgtu, kamēr nav apstiprināts reālais piegādātājs/API.',
    'Stage 2.': '2. posms.', 'Stage 2: CSV import.': '2. posms: CSV imports.',
    'Stage 2: CSV/API import into timber_movements.': '2. posms: CSV/API imports kokmateriālu pārvietošanā.',
    'Live token-check already exists via /api/satellite/token-check.': 'Tiešsaistes atslēgas pārbaude jau pieejama (/api/satellite/token-check).',
    'No records synced yet.': 'Vēl nav sinhronizētu ierakstu.', 'Connect failed': 'Pieslēgšana neizdevās',
    'Disconnect failed': 'Atslēgšana neizdevās', 'Sync failed': 'Sinhronizācija neizdevās', 'Test failed': 'Pārbaude neizdevās',
    'Reset failed': 'Atiestatīšana neizdevās', 'Demo-интеграции': 'Demo integrācijas', 'Подключено': 'Pieslēgts',
    'Кредиты': 'Piekļuves dati', 'Ошибки': 'Kļūdas', 'Получено записей': 'Saņemtie ieraksti', 'Записей получено': 'Saņemtie ieraksti',
    'Последняя синхронизация': 'Pēdējā sinhronizācija', 'по всем интеграциям': 'visās integrācijās', 'в месяц': 'mēnesī',
    'периодичность': 'biežums', 'не смешиваются с продакшеном': 'netiek jauktas ar ražošanas datiem',
    'Нет интеграций в этой категории': 'Šajā kategorijā nav integrāciju', 'в каталоге': 'katalogā',
    'satellite': 'satelīts', 'machine': 'mašīna', 'fleet': 'autoparks', 'gis': 'ĢIS', 'erp': 'ERP',
    'timber': 'kokmateriāli', 'weighbridge': 'svari', 'generic': 'vispārīgs', 'audit': 'audits', 'worker': 'darbinieks',
    'KRAUZERS (exact vendor TBD': 'KRAUZERS (piegādātājs tiks precizēts',
    'Already live in production via bot.py — this catalog entry documents it, it is not managed through the generic adapter sync pipeline.':
      'Jau darbojas ikdienā caur Forest AI Telegram botu.',
    'KRAUZERS is confirmed to use GPS/electronic fleet systems for timber trucks; the exact software vendor is not yet confirmed — do not name a specific product.':
      'KRAUZERS kokvedējiem izmanto GPS/elektroniskās autoparka sistēmas; konkrētais programmatūras piegādātājs vēl tiek precizēts.',
    'TIMBRO is confirmed to use or be developing a forest audit system (LiDAR + GNSS + camera photofixation + estimation algorithms). No API/data contract is confirmed yet — do not mark Connected.':
      'TIMBRO izmanto vai izstrādā meža audita sistēmu (LiDAR + GNSS + foto fiksācija + novērtēšanas algoritmi). API un datu apmaiņas kārtība vēl nav saskaņota.',

    // ── Dialogs (alert / confirm / prompt) ───────────────────────────────
    'Нужно минимум 3 точки, чтобы сохранить полигон.': 'Lai saglabātu poligonu, nepieciešami vismaz 3 punkti.',
    'Название объекта (например: Mūrnieku Jāņa 0.21ha):': 'Objekta nosaukums (piem., Mūrnieku Jāņa 0.21ha):',
    'Название сектора (например: S-004):': 'Sektora nosaukums (piem., S-004):',
    'Отключить интеграцию? История синхронизации и логи сохранятся — подключить можно снова в любой момент.':
      'Atslēgt integrāciju? Sinhronizācijas vēsture un žurnāli tiks saglabāti — pieslēgt var atkal jebkurā brīdī.',
    'Сбросить demo-данные этой интеграции? Реальные операционные данные не затрагиваются.':
      'Atiestatīt šīs integrācijas demo datus? Reālie operacionālie dati netiek ietekmēti.'
  };

  // Strings built around a number or name. Applied to the whole text, or to the
  // text after a leading icon. Replacement uses $1, $2 like String.replace.
  var PATTERNS = [
    [/^(\d+) критических$/, '$1 kritiski'],
    [/^(\d+) рейсов$/, '$1 reisi'],
    [/^(\d+) фото$/, '$1 foto'],
    [/^([\d.,\s]+) m³ под риском$/, '$1 m³ apdraudēti'],
    [/^(\d+) (HIGH|MEDIUM|LOW)$/, function (m, n, l) { return n + ' ' + EXACT[l]; }],
    [/^AI-оценка по (\d+) зарегистрированным инцидентам$/, 'AI novērtējums pēc $1 reģistrētiem incidentiem'],
    [/^агрегированная оценка по всем (\d+) секторам$/, 'apkopots novērtējums visiem $1 sektoriem'],
    [/^из (\d+) в каталоге$/, 'no $1 katalogā'],
    [/^(\d+) из (\d+)$/, '$1 no $2'],
    [/^(\d+) точек$/, '$1 punkti'],
    [/^Risk #(\d+) — (.+)$/, 'Risks #$1 — $2'],
    [/^(.+?) — ([A-Z][A-Z_]+)(?: \(([^)]*)\))?$/, function (m, when, code, actor) {
      if (!Object.prototype.hasOwnProperty.call(EXACT, code)) return m;
      var a = actor === undefined ? '' : ' (' + (Object.prototype.hasOwnProperty.call(EXACT, actor) ? EXACT[actor] : actor) + ')';
      return when + ' — ' + EXACT[code] + a;
    }],
    [/^across (\d+) risks?$/, function (m, n) { return n === '1' ? '1 riskā' : n + ' riskos'; }],
    [/^(\d+) HIGH risk\(s\) registered$/, '$1 reģistrēti AUGSTI riski'],
    [/^(\d+) GPS check-in\(s\) rejected$/, '$1 GPS reģistrēšanās noraidītas'],
    [/^(\d+) timber movement\(s\) with missing volume$/, '$1 kokmateriālu pārvietošanas bez apjoma'],
    [/^(\d+) sector\(s\)$/, '$1 sektori'],
    [/^(\d+) sector\(s\) shown$/, 'parādīti $1 sektori'],
    [/^([\d.,]+) ha total$/, 'kopā $1 ha'],
    [/^site · (.+)$/, 'objekts · $1'],
    [/^ESTIMATED FINANCIAL EXPOSURE: (.+)$/, 'PROGNOZĒTIE FINANŠU ZAUDĒJUMI: $1'],
    [/^TOTAL ESTIMATED EXPOSURE: (.+)$/, 'KOPĀ PROGNOZĒTIE FINANŠU ZAUDĒJUMI: $1'],
    [/^✓ (\d+)pts$/, '✓ $1 pkt.'],
    [/^(\d+) pts$/, '$1 pkt.'],
    [/^Worker (.+?) left sector boundary(.*)$/, 'Darbinieks $1 atstāja sektora robežu$2'],
    [/^Сектор (.+) создан и автоматически привязан к реальным GPS-координатам \(масштаб взят из этого плана\)\.?$/,
      'Sektors $1 izveidots un automātiski piesaistīts reālām GPS koordinātām (mērogs ņemts no šī plāna).'],
    [/^🔄 Reset OK — удалено записей: (\d+), инцидентов: (\d+)$/, '🔄 Atiestatīts — dzēsti ieraksti: $1, incidenti: $2'],
    [/^✅ Отправлено, инцидент #(\d+)(.*)$/, '✅ Nosūtīts, incidents #$1$2']
  ];

  // Dialog messages are often "<known prefix>: <server error>".
  var PREFIXES = {
    'Ошибка': 'Kļūda', 'Connect failed': 'Pieslēgšana neizdevās', 'Disconnect failed': 'Atslēgšana neizdevās',
    'Failed': 'Neizdevās', 'Reset failed': 'Atiestatīšana neizdevās', 'Sync failed': 'Sinhronizācija neizdevās',
    'Test failed': 'Pārbaude neizdevās', '⚠ Retry failed': '⚠ Atkārtošana neizdevās', '⚠ Upload failed': '⚠ Augšupielāde neizdevās',
    'Request failed (HTTP': 'Pieprasījums neizdevās (HTTP'
  };

  var LEAD = /^([^0-9A-Za-zÀ-žЀ-ӿ]*)([\s\S]*?)([\s:.…·]*)$/;

  function lookup(t) {
    if (Object.prototype.hasOwnProperty.call(EXACT, t)) return EXACT[t];
    for (var i = 0; i < PATTERNS.length; i++) {
      var p = PATTERNS[i];
      if (p[0].test(t)) return t.replace(p[0], p[1]);
    }
    return null;
  }

  function lookupLead(t) {
    var r = lookup(t);
    if (r !== null) return r;
    var m = LEAD.exec(t);
    if (m && (m[1] || m[3]) && m[2]) {
      r = lookup(m[2]); if (r !== null) return m[1] + r + m[3];
      if (m[1] && m[3]) { r = lookup(m[2] + m[3]); if (r !== null) return m[1] + r; }
    }
    return null;
  }

  // Translate one piece of UI text; returns null if unknown.
  function trCore(t) {
    var r = lookup(t);
    if (r !== null) return r;
    r = lookupLead(t);                          // "⚠ Risk", "Status:", "← Back", "ℹ Text."
    if (r !== null) return r;
    if (t.indexOf(' · ') > 0) {                 // "Rigas Mezi · ACTIVE"
      var parts = t.split(' · '), changed = false;
      for (var j = 0; j < parts.length; j++) {
        var q = parts[j].trim() ? lookupLead(parts[j].trim()) : null;
        if (q !== null) { parts[j] = parts[j].replace(parts[j].trim(), function () { return q; }); changed = true; }
      }
      if (changed) return parts.join(' · ');
    }
    return null;
  }

  function tr(s) {
    if (s == null) return s;
    var norm = String(s).replace(/\s+/g, ' ').trim();
    if (!norm || norm.length > 400) return s;
    var r = trCore(norm);
    if (r === null) return s;
    var lead = String(s).match(/^\s*/)[0], tail = String(s).match(/\s*$/)[0];
    return lead + r + tail;
  }

  function trMessage(msg) {
    if (msg == null) return msg;
    var s = String(msg), r = tr(s);
    if (r !== s) return r;
    for (var k in PREFIXES) {
      if (s.indexOf(k) === 0 && /^[:\s]/.test(s.slice(k.length))) return PREFIXES[k] + s.slice(k.length);
    }
    return s;
  }

  // ── DOM ──────────────────────────────────────────────────────────────────
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1, CODE: 1, PRE: 1 };
  var ATTRS = ['placeholder', 'title', 'aria-label'];

  // forText=true: also skip text inside SCRIPT/STYLE/TEXTAREA/contenteditable.
  // Attributes (placeholder/title) of TEXTAREA/INPUT are UI and are translated.
  function skipped(el, forText) {
    for (var e = el; e && e.nodeType === 1; e = e.parentElement) {
      if (forText && (SKIP_TAGS[e.tagName] || e.isContentEditable)) return true;
      if (e.hasAttribute('data-no-i18n')) return true;
      if (e.classList && e.classList.contains('leaflet-control-attribution')) return true;
    }
    return false;
  }

  function translateText(node) {
    var p = node.parentElement;
    if (!p || skipped(p, true)) return;
    var v = node.nodeValue, r = tr(v);
    if (r !== v) node.nodeValue = r;
  }

  function translateAttrs(el) {
    if (skipped(el, false)) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var a = ATTRS[i], v = el.getAttribute(a);
      if (v) { var r = tr(v); if (r !== v) el.setAttribute(a, r); }
    }
    if (el.tagName === 'INPUT' && (el.type === 'button' || el.type === 'submit') && el.value) {
      var rv = tr(el.value); if (rv !== el.value) el.value = rv;
    }
  }

  function translateTree(root) {
    if (!root) return;
    if (root.nodeType === 3) { translateText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1) translateAttrs(root);
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    var n;
    while ((n = w.nextNode())) {
      if (n.nodeType === 3) translateText(n); else translateAttrs(n);
    }
  }

  var busy = false;
  function onMutations(list) {
    if (busy) return;
    busy = true;
    try {
      for (var i = 0; i < list.length; i++) {
        var m = list[i];
        if (m.type === 'childList') {
          for (var j = 0; j < m.addedNodes.length; j++) translateTree(m.addedNodes[j]);
        } else if (m.type === 'characterData') {
          translateText(m.target);
        } else if (m.type === 'attributes' && m.target.nodeType === 1) {
          translateAttrs(m.target);
        }
      }
    } finally { busy = false; }
  }

  function start() {
    document.documentElement.setAttribute('lang', 'lv');
    translateTree(document.body);
    new MutationObserver(onMutations).observe(document.body, {
      childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS
    });
  }

  // ── Dialogs ──────────────────────────────────────────────────────────────
  var _alert = window.alert, _confirm = window.confirm, _prompt = window.prompt;
  window.alert = function (m) { return _alert.call(window, trMessage(m)); };
  window.confirm = function (m) { return _confirm.call(window, trMessage(m)); };
  window.prompt = function (m, d) { return _prompt.call(window, trMessage(m), d); };

  // ── Dates: default locale lv-LV when the code passes none ────────────────
  ['toLocaleString', 'toLocaleDateString', 'toLocaleTimeString'].forEach(function (fn) {
    var orig = Date.prototype[fn];
    Date.prototype[fn] = function (locales, options) {
      return orig.call(this, locales === undefined ? 'lv-LV' : locales, options);
    };
  });

  // ── Chart.js: translate dataset labels, axis/legend titles ───────────────
  function trChartConfig(cfg) {
    if (!cfg || !cfg.data) return cfg;
    (cfg.data.datasets || []).forEach(function (ds) { if (typeof ds.label === 'string') ds.label = tr(ds.label); });
    if (Array.isArray(cfg.data.labels)) cfg.data.labels = cfg.data.labels.map(function (l) { return typeof l === 'string' ? tr(l) : l; });
    var o = cfg.options || {}, pl = o.plugins || {};
    if (pl.title && typeof pl.title.text === 'string') pl.title.text = tr(pl.title.text);
    var sc = o.scales || {};
    Object.keys(sc).forEach(function (k) { if (sc[k] && sc[k].title && typeof sc[k].title.text === 'string') sc[k].title.text = tr(sc[k].title.text); });
    return cfg;
  }
  if (typeof window.Chart === 'function') {
    var OrigChart = window.Chart;
    var Wrapped = function (ctx, cfg) { return new OrigChart(ctx, trChartConfig(cfg)); };
    Object.setPrototypeOf(Wrapped, OrigChart);
    Wrapped.prototype = OrigChart.prototype;
    window.Chart = Wrapped;
  }

  window.ForestI18n = { tr: tr, trMessage: trMessage, lang: 'lv' };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
