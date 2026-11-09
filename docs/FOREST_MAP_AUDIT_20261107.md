# Meža kartes pilnais audits — 2026-11-07

## Kopsavilkums

Pārbaudīju esošo vietējo VMD/VZD katalogu, Meža kartes API, LVM GEO kadastra meklēšanu, sektoru priekšskatījumu un pārlūka attēlošanu. Avota datubāzes netika importētas vai mainītas; produkcijas serviss netika pārstartēts. Izolētais kandidāts balstās verificētajā aktīvajā Meža kartes laidienā, nevis Git HEAD.

| Pārbaude | Rezultāts |
|---|---|
| VMD/VZD datu kopa | PASS — 3 063 409 nogabali, 1 055 666 zemes vienības; `PRAGMA quick_check=ok` |
| Kopīgā LVM GEO / Meža kartes validācija | PASS — piecos Latvijas reģionu piemēros identiska sākotnējā ģeometrija un validācijas lauki |
| Kadastra meklēšana | PASS — precīzs 11 ciparu meklējums, VMD avota ID, koordinātu identificēšana, pašvaldību katalogs un lapošana |
| Kartes renderēšana | PASS — pieci reģioni, flīzes, slāņi, klikšķis, tālummaiņa, pārvietošana un atlase |
| Sektoru priekšskatījums | PASS — piecu nogabalu DRY-RUN; 0 faktisku importu |
| Esošie sektori | FAIL — 13/21 parādāmi, 8 nav lietojamas atrašanās vietas; koordinātu pārbaudei nav Latvijas robežas avota |
| Produkcijas gatavība | NO — nav teritorijas zīmēšanas atlases un nav autoritatīvas Latvijas robežas slāņa; pilnā VMD regresiju kopa nav pabeigta |

## Sistēmas salīdzinājums un izmaiņas

Forest Map un LVM GEO izmanto vienu `nationwide.compartment_validation()` pārbaudi. Precīzās kadastra asociācijas, VZD ģeometrijas pārbaude, pārklājuma procenti, ārpus robežas laukums un reģistrācijas atļauja vairs netiek aprēķināti divās atšķirīgās Forest Map/LVM GEO loģikās. Abi meklēšanas ceļi tagad atgriež to pašu neapaļoto validācijas objektu un to pašu avota ģeometriju, transformētu no avota KRS uz WGS84. Vienkāršotās flīzes paliek atsevišķs attēlošanas slānis; imports no jauna nolasa sākotnējo avotu.

Novērstās kļūdas: LV režīms sākotnēji atvērās angliski, koordinātu meklēšana tikai pārvietoja karti bez identificēšanas, pašvaldību/VMD ID katalogs trūka, rezultātu navigācijai trūka iepriekšējās lapas, kadastra rezultāti netika izcelti kartē, atlasīto slāni nevarēja ieslēgt/izslēgt, un atrastā VZD robeža nepakļāvās slāņa pārslēgšanai. Reģistrācijas vārda/uzvārda lauki pārvietoti uz reģistrācijas soli ar organizācijas apstiprinājumu. Zemā mēroga kvadrāti aizstāti ar skaidri marķētiem avota robežtaisnstūra centru klātbūtnes punktiem.

Pārlūka pārbaudes laikā tika atrasts arī izpildlaika `async is not defined` (palicis tukšs tokens pēc koda ievietošanas); tas tika noņemts un atkārtota pilnā pārbaude izgāja. Pašvaldību katalogs izmanto precīzu `adm1` vērtību un indeksētu, 100 ierakstu lapu.

### 20 pārbaudītie reālie kadastra apzīmējumi

Apzīmējumi atlasīti tikai no vietējā avota un satur nogabalus. Reģionu dalījums un pilnais pārbaudes pieraksts ir [izvēles pierādījumos](evidence/vmd-real-world-20261107/selection.json).

| Reģions | Pašvaldība | Pagasts | Kadastrs | Nogabali | Platība ha |
|---|---|---|---:|---:|---:|
| Vidzeme | Valmieras novads | Burtnieku pagasts | `96480160030` | 25 | 19.63 |
| Vidzeme | Cēsu novads | Amatas pagasts | `42420010146` | 25 | 13.52 |
| Vidzeme | Smiltenes novads | Launkalnes pagasts | `94700040023` | 25 | 13.77 |
| Vidzeme | Alūksnes novads | Alsviķu pagasts | `36420040017` | 25 | 23.16 |
| Vidzeme | Gulbenes novads | Lejasciema pagasts | `50640020008` | 25 | 17.83 |
| Latgale | Ludzas novads | Istras pagasts | `68600020035` | 25 | 29.02 |
| Latgale | Rēzeknes novads | Mākoņkalna pagasts | `78720010031` | 25 | 30.44 |
| Latgale | Krāslavas novads | Indras pagasts | `60620022173` | 26 | 39.20 |
| Latgale | Preiļu novads | Aglonas pagasts | `76420050155` | 25 | 29.45 |
| Latgale | Balvu novads | Baltinavas pagasts | `38440020151` | 24 | 20.11 |
| Kurzeme | Ventspils novads | Tārgales pagasts | `98660020099` | 25 | 14.39 |
| Kurzeme | Kuldīgas novads | Alsungas pagasts | `62420110056` | 25 | 46.68 |
| Kurzeme | Talsu novads | Dundagas pagasts | `88500020032` | 25 | 16.93 |
| Kurzeme | Dienvidkurzemes novads | Rucavas pagasts | `64840080332` | 25 | 18.57 |
| Kurzeme | Saldus novads | Nīgrandes pagasts | `84700030005` | 25 | 27.06 |
| Zemgale | Dobeles novads | Tērvetes pagasts | `46880010410` | 24 | 11.65 |
| Zemgale | Jelgavas novads | Elejas pagasts | `54480090003` | 22 | 33.00 |
| Zemgale | Bauskas novads | Iecavas pagasts | `40640020105` | 25 | 16.33 |
| Zemgale | Ķekavas novads | Daugmales pagasts | `80560020116` | 26 | 29.65 |
| Zemgale | Ogres novads | Birzgales pagasts | `74440030154` | 25 | 19.76 |

Pieci reprezentatīvie API piemēri (Rīga, Vidzeme, Latgale, Kurzeme, Zemgale) tika tieši salīdzināti starp LVM GEO `/api/geodata/vmd/cadastre` un Forest Map `/feature`: avota ID, kadastrs, kvartāls, nogabals, platība, sākotnējā ģeometrija un validācijas lauki sakrita visos piecos. Precīzā ģeometrija tika salīdzināta ar `equals_exact(..., 0)`. [Salīdzinājuma JSON](evidence/forest-map-audit-20261107/data-parity.json).

## Kadastra, koordinātu un kataloga meklēšana

- Precīzs kadastrs paliek caur esošo `/api/geodata/vmd/cadastre`; telpiskie kandidāti tiek rādīti atsevišķi un nav reģistrējami.
- VMD avota ID meklēšana ierobežota līdz `VMD:` prefiksam un nolasa pilno avota ierakstu caur `/feature`.
- Koordinātu meklēšana validē Latvijas koordinātu apgabalu, pietuvina karti un izsauc `/identify`.
- Pašvaldības katalogs izmanto `adm1=?`, SQLite indeksu `location_idx`, 100 ierakstu lapas un precīzu avota ID klikšķim. Iepriekšējā/nākamā lapa tiek rādīta ar kopskaitu.
- Pārvietojot karti, atceltie flīžu pieprasījumi tiek pārtraukti; flīžu/klienta atbilžu apjoms ir ierobežots. Kadastra, VMD un pašvaldības meklēšana izmanto lokālo datubāzi; netiek lejupielādēts pilns katalogs.

Piecu reģionu pilno kadastra meklējumu tiešie laiki bija 1,88–4,48 s (vidēji 3,53 s; pilna avota atribūtu un robežu pārbaude, nevis tikai HTTP laiks). To ietekmē vienas kadastra zemes vienības telpiski kandidāti un sākotnējo ģeometriju pārbaude; rezultāti ir vienas mašīnas mērījumi.

## Ģeometrija un robežu neatbilstības

- Kopā 3 063 409 VMD nogabali; 1 723 `geometry_valid=0`; 2 152 rindām ir `repair` atzīme. Avota ģeometrija ir EPSG:10306; Leaflet koordinātas ir EPSG:4326.
- Skaitļu starpība ir izskaidrota ingest koda un DB grupējuma pārbaudē: 1 717 rindām ir `Source invalid; display-only make_valid`, 435 — `Display normalization repair; original preserved`. No pēdējām 429 ir sākotnēji derīgas un 6 — sākotnēji nederīgas. Tātad 2 152 atzīmes ietver 429 derīgu avotu attēlojuma normalizācijas gadījumus; tās nav 2 152 nederīgi sākotnējie poligoni.
- `original_geometry` / `native_geometry` un normalizētā `geometry` ir atsevišķi lauki. Importētājs saglabā abus; karte neizmanto attēlojuma ģeometriju reģistrācijai. Source DB failu izmērs un `mtime` pirms/pēc pārlūka testa sakrita.
- 20 lokālo kadastra vienību auditā bija 497 precīzi VMD nogabali. 279 ģeometrijas/kadastra validācijas ļāva reģistrāciju, bet viens jau esošs sektors nav atkārtoti importējams; 278 bija jauni importējami ieraksti. 218 nogabaliem bija pozitīvs ārpus robežas laukums virs 1e-9 m² un stingrā `parcel.covers()` pārbaude tos bloķēja. Vēl 90 gadījumos bija tikai ≤1e-9 m² peldošā komata atlikums; `covers()` tos atļāva. Slieksnis netika mainīts.
- Lielākā novērotā atšķirība šajos 497 ierakstos: `VMD:nodala2855:60176626`, `78720010031`, pārklājums 98.62144976543024%, ārpus zemes vienības 409.2693362251375 m². Tas ir reāls avota robežu pārklāšanās/nesakritības gadījums, nevis noapaļošana; tas paliek bloķēts pārbaudei. Mazāku pozitīvu slāņu gadījumus automātiski neapstiprinām.
- Sākotnējie nederīgie poligoni netiek salaboti validācijas vai importa laikā. Display-only flīzēs tie ir atzīmēti oranži un netiek atlasīti reģistrācijai.

## Valsts mēroga renderēšana un veiktspēja

Pārlūka tests aptvēra Rīgu un četrus reģionus. Visos piecos: kartes atvēršana, meklēšana, klikšķis, pan, zoom, slāņu pārslēgšana un atlase — PASS. Atvēršanās 1,88 s; 816 flīzes; maksimāli 46 758 baiti un 236 elementi vienā klienta flīzē; 27 novecojuši pieprasījumi atcelti; 0 flīžu kļūdu. Maksimālais animācijas kadra intervāls 91,2 ms; maksimālais novērotais JS ilgais uzdevums 139 ms. Kartei nebija sastinguma, tomēr 297 ms ir uzlabojama pīķa vērtība. [Pilns pārlūka/performance pierādījums](evidence/forest-map-audit-20261107/acceptance.json).

| Zoom | Reizes | Vidējais ms | Maksimālais ms | Maks. baiti | Maks. objekti |
|---:|---:|---:|---:|---:|---:|
| 6 | 10 | 2.91 | 24.57 | 29,328 | 147 |
| 9 | 10 | 10.31 | 26.98 | 50,797 | 256 |
| 11 | 10 | 6.93 | 19.65 | 12,966 | 64 |
| 13 | 10 | 40.75 | 144.82 | 208,715 | 454 |
| 16 | 10 | 2.37 | 10.32 | 16,564 | 29 |

Zemā mērogā ir centru klātbūtnes punkti, nevis kvadrāti/poligoni: to atrašanās vieta ir avota nogabalu robežtaisnstūru centru vispārinājums, nevis precīzs meža pārklājums. Saskares un ūdens/robežu precizitāte netiek apgalvota. Vidējā/tuvā mērogā lieto telpiski ierobežotas, vienkāršotas GeoJSON Canvas flīzes; VZD robežas no 14. zoom. MVT maiņa netika veikta: esošais renderētājs katrai flīzei paliek zem 600 elementiem un 400 KB, un šis mērījums nedod pierādījumu, ka MVT būtu nepieciešams pirms produkcijas slodzes testa.

## Esošo sektoru audits

Operational datubāzē ir 21 sektors. API atgriež 13/21: pieci nav novietojami (ID 1, 18, 19, 20, 21 — nav robežas un nav saglabāta centra); trīs ir ārpus pašreizējā Latvijas kartes apgabala (15 un 16 nederīgas robežas, 17 derīga ģeometrija ārpus apgabala). Sektors 13 tiek rādīts tikai kā saglabāts centra punkts, jo robeža ir nederīga. Kopā trīs nederīgas robežas, viens centra marķieris un trīs ārpus apgabala. Visiem 21 ir `organization_id=1`; API filtrē pēc autentificētās organizācijas. CRS kolonna sektoros nav — API pieņem WGS84 `[lat,lon]` formātu un pārveido GeoJSON `[lon,lat]`.

No avota nav pieejama Latvijas administratīvās robežas ģeometrija. Tādēļ koda vēsturiskā pārbaude tikai pret kartes koordinātu aploksni nav pietiekama, lai pierādītu atrašanos Latvijā. Sektors 9 (aptuveni 58.867916 N, 28.713921 E) ietilpst šajā aploksnē, taču tā atrašanās Latvijā nav validēta. Tagad kartes brīdinājums to pasaka; sektoru dati nav mainīti. Pilns ID līmeņa pārskats: [sector-audit.json](evidence/forest-map-audit-20261107/sector-audit.json).

## Atlase, reģistrācija un drošība

Atlasīt, pievienot, noņemt un notīrīt līdz 100 derīgus nogabalus; redzams skaits un platība. Reģistrācijas dialogā prasa sektora nosaukumu, atbildīgās personas vārdu/uzvārdu un pareizās organizācijas apstiprinājumu. DRY-RUN izmanto esošo `/api/geodata/vmd/import-selected`; reāla izveide prasa atsevišķu apstiprinājumu. Pārlūka tests sagatavoja piecus sektoru grupējumus/piecus nogabalus; preview atļāva tikai `dry_run:true`, rakstīšanas mēģinājums saņēma HTTP 403. Netika veikta reāla reģistrācija.

Anonīma API piekļuve atgrieza 401; sektoru slānis ir organizācijas filtrēts un `private, no-store`. Esošais produkts izmanto vienu organizāciju ar koplietotu Basic Auth identitāti; ja vajadzīgs multi-tenant lietojums, to nevar uzskatīt par pilnvērtīgi pierādītu individuālu lietotāju izolāciju bez esošās kontu/autorizācijas infrastruktūras. Klientu GPS un riska dati nacionālā slāņa atbildēs netiek iekļauti. Visu operacionālās DB tabulu skaits un fingerprint pirms/pēc pieņemšanas testa sakrita; 21 sektora fingerprint nemainījās: `1585dfeb6373cead7f2f8f4f4f37f2cd20dcc0e6f9f4b1175dfceb7dfff4db26`.

## Pārbaudes

- PASS — kandidāta Python: `tests/test_forest_map.py` + `tests/test_nationwide_geodata.py`: 26 testi.
- PASS — esošais VMD/LVM GEO UI: `node tests/test_vmd_local_ui.js` 7/7; `node tests/test_vmd_production_ui.js` 16/16.
- PASS — četras mērķētas sektoru reģistrācijas/backend regresijas: DRY-RUN/dublikāti, kopīgais import preview, precīza 11 ciparu prasība, nepārbaudīta kadastra bloķēšana (4/4).
- PASS — pilns izolētais pārlūka tests: 5 reģioni, autentifikācija, kadastra/koordinātu/VMD ID/pašvaldības katalogs, lapošana, slāņi, klikšķis, atlase, reģistrācijas preview, LV sākuma režīms; 0 browser/tiles kļūdu; operacionālie dati nemainīti.
- PASS — `node --check` un Python kompilācija.
- NOT RUN TO COMPLETION — viss `tests/test_vmd_production.py` komplekts šajā sesijā nedeva kopsavilkumu pirms ilgā palaišanas loga; četri tiešie ar reģistrāciju saistītie testi ir PASS. Pilno komplektu jāizpilda pirms produkcijas.
- Brīdinājumi no esošā koda: `datetime.utcnow()` un FastAPI `on_event` deprecated; nav bloķējoši Meža kartes datiem.

## Izolētais laidiens un produkcijas drošība

Kandidāta direktorija: `/root/forest_ai/releases/forest-api-forest-map-audit-20261107T1645Z`. Tā kopēta no verificētā aktīvā Meža kartes laidiena `/root/forest_ai/releases/forest-api-meza-karte-20261107T084300Z`, nevis Git HEAD, un ietver tikai trīs lietojumprogrammas failus: `assets/forest-map.js`, `services/geodata/nationwide.py`, `services/geodata/forest_map.py`. Kontrolsumma katram failam ir `forest-map-release-candidate.json`. Kandidāts nesatur DB migrācijas un nepalaiž importu. Tā data saite ir produkcijas datu direktorija; testēšana notika ar preview utilītu, kas izveido operacionālās DB pagaidu kopiju un bloķē rakstīšanu.

Pirms aktivizēšanas jāizveido jauns timestamped koda/pašreizējās systemd konfigurācijas un operacionālo datu backup. Iepriekšējā laidiena backup ir `/root/forest_ai/data/backups/forest_api_meza_activation_20261107T0852Z`, bet pašreizējais rollback mērķis šim atjauninājumam ir esošais Meža kartes laidiens `/root/forest_ai/releases/forest-api-meza-karte-20261107T084300Z`, nevis pirms-Meža-kartes baseline. Neatjaunot vecu DB kopiju pāri jaunām lietotāju izmaiņām.

Šajā sesijā ražošanas restartu neveicu. Host `systemctl` bus piekļuve sandbox vidē atgrieza `Failed to connect to bus: Operation not permitted`, tāpēc šodienas servisa PID/WorkingDirectory atkārtota pārbaude nav pieejama; bāzlīnija un iepriekšējais aktivācijas statuss ņemts no iepriekšējā verificētā aktivācijas pieraksta (`dfbf12feae50` bija pirmskartes runtime bāze, aktīvais release backend `552c46ae547b`). Pirms jebkuras aktivizēšanas šī pārbaude jāatkārto administratīvā vidē. Iepriekšējais pieraksts ziņoja Sentinel-1/2 INACTIVE; šajā auditā tie netika palaisti, modificēti vai izsaukti.

### Bloķētāji pirms produkcijas

1. Nav taisnstūra/poligona zīmēšanas atlases rīku; tādēļ selekcija pēc teritorijas nav izpildīta un šajā laidienā nav jāuzskata par pabeigtu.
2. Nav autoritatīva Latvijas valsts robežas slāņa. Esošo sektoru pārbaude pret koordinātu aploksni ir nepietiekama; sektoru 9 atrašanās Latvijā nav pierādīta.
3. Pilnais VMD production regresiju komplekts nav pabeigts, un fresh `systemctl`/konfigurācijas/backup pārbaude jāveic pirms restartēšanas.

**PRODUCTION READY: NO.** Kandidāts ir review/staging gatavs, bet aktivizēšanu neveikt līdz bloķētāju noslēgšanai.

### Aktivizācijas / rollback soļi pēc bloķētāju novēršanas un atsevišķa apstiprinājuma

1. Pirms darbības pārbaudīt `systemctl show forest-api.service -p MainPID -p WorkingDirectory -p ExecStart`, faktiskā procesa kodu, `ss` portu 8000, disk/memory, konfigurāciju, autentifikāciju, datubāzes read-only režīmu, Sentinel timer/service statusu un visu kritisko endpointu health. Apstiprināt, ka pašreizējais darbojošais kods joprojām ir norādītais Meža kartes release.
2. Izveidot jaunu timestamped backup pašreizējam runtime kodam, systemd drop-in/env konfigurācijai un SQLite backup ar `sqlite3.Connection.backup`; saglabāt 0600/0700. Fiksēt 21 sektora un tabulu fingerprint. Rollback mērķis: pašreizējais Meža kartes release.
3. Kandidātu vispirms palaist loopback portā ar pagaidu operacionālās DB kopiju un VMD/VZD read-only failiem; palaist pilnu VMD regresiju un health/auth/search/map/preview pārbaudes. Nekad nestartēt otro API uz 8000.
4. Pēc atsevišķa apstiprinājuma nomainīt tikai `forest-api.service` WorkingDirectory uz kandidātu, saglabājot esošo environment/geodata manifest; `systemctl daemon-reload`, kontrolēti restartēt vienu servisu, pārbaudīt dashboard, Map, Sectors, GPS, Risks, integrācijas, VMD/VZD, Meža karti un datubāzes fingerprint.
5. Ja health vai datu pārbaude neizdodas: atjaunot iepriekšējo drop-in uz `/root/forest_ai/releases/forest-api-meza-karte-20261107T084300Z`, `daemon-reload`, restartēt vienu servisu; pārbaudīt health. Neatjaunot DB backup, ja vien atsevišķa datu atjaunošana nav apstiprināta.

**SENTINEL-1: NOT ACTIVATED. SENTINEL-2: NOT ACTIVATED.**
