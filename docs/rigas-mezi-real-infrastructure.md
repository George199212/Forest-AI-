# Rīgas meži — Real Digital Infrastructure (Discovery Report)

Status: research only, no implementation
Date: 2026-10-13
Method: public sources only (reports, public profiles, vendor sites). No authentication, no probing of non-public endpoints.

Confidence scale: **CONFIRMED** (explicit public source) · **HIGHLY LIKELY** (strong indirect evidence) · **POSSIBLE** (technically plausible, no evidence) · **UNKNOWN** (no evidence found) · **REQUIRES CLIENT CONFIRMATION**

---

## 0. Primary source

Almost all CONFIRMED findings come from one document:

**LAD56 project final report (2025)**: "Mežizstrādes automatizētas plānošanas algoritmu, datu apstrādes un analīzes IT rīka izstrāde…", project no. 23-00-A01612-000004, period 2023-07-04 → 2025-06-30.
Partners: LBTU, SIA Rīgas Meži, MeKA, LU ĢZZF, SIA SunGIS, LMS, Pierīgas partnerība, SIA Niedrāji MR, SIA RGP.
Section 3, "Rīgas Meži SIA mežu īpašumu datu pārvaldības IS izvērtējums", was written with Rīgas meži as the responsible partner.
URL: https://laukutikls.lv/wp-content/uploads/2025/07/LAD56_nosleguma_zinojums.pdf

Caveat: the report describes the state as of 2023–2025. Anything may have changed since. Every CONFIRMED item below is still subject to a quick client sanity check.

---

## 1. Key findings (summary)

1. **MDPS is a single central PostgreSQL database**, created in 2017. It is not a set of separate systems. FOREMS (desktop) and Go GIS (web) are two **front-ends** on that database. — CONFIRMED
2. **QGIS connects directly to the central database** and can edit data. — CONFIRMED
3. **QField and IntraMaps Roam are NOT connected to the central DB.** They receive data as **GeoPackage (.gpkg)** packages prepared from it. — CONFIRMED
4. **Palma Timber handles harvest planning, work orders and machine data.** Work orders are PDFs. Harvested volumes come back from machines in **StanForD** format and are imported into the IS for settlement. — CONFIRMED
5. **Forest inventory is synced with the VMD Meža valsts reģistrs (MVR)**, and the DB structure matches MVR. — CONFIRMED
6. **Rīgas meži already verifies harvesting with Sentinel-2.** In the LAD56 test harvest (Juglas mežniecība, quarters 215–216) they compared the technological map against Sentinel-2 imagery after harvest. — CONFIRMED
   → Forest AI does not need to convince them that satellite verification is valuable. They already do it manually. Forest AI automates it and runs it continuously.
7. **Rīgas meži has had the status "commercial company significant for national security" since 2021.** — CONFIRMED (lvportals.lv)
   → This is the single biggest constraint on integration architecture (see §4).
8. Rīgas meži publishes code on GitHub: `rigasmezi/Forest-harvest-planner` (Python) and `rigasmezi/oin_project` ("OIN generator", C#). — CONFIRMED
   OIN = digital harvesting work order format generated from MDPS for forest machines (stated in LAD56).

---

## 2. System-by-system

### 2.1 MDPS — Meža datu pārvaldības sistēma

| Field | Value |
|---|---|
| PURPOSE | Central forest data management: properties, maps, harvest planning and supervision |
| VENDOR | UNKNOWN as a whole. Web front-end is Go GIS (SunGIS); desktop front-end is FOREMS (vendor unknown) |
| CONFIRMED USE | CONFIRMED. Created 2017. Operations logged in MDPS since 2019 |
| DATA AVAILABLE | CONFIRMED categories: forest inventory map edits; property text data; land parcel text + spatial; **forest stand (nogabals) text + spatial**; map points/lines; **forestry operations text + spatial**; protected areas (ĪADT); fire-affected areas; RM biotopes; nature protection objects; ĪADT, micro-reserves and buffers; DAP Ozols biotopes; **cutting areas (cirsmas) spatial**; inventory process data; **RM structural unit (mežniecība) territories**; user measurements; user connection details; max allowable cut calculations; landscape design plans; biotope management plans |
| INTEGRATION OPTIONS | PostgreSQL direct (exists for QGIS); GeoPackage export (exists for QField/Roam); Go GIS web services (UNKNOWN). Public REST/WMS/WFS: UNKNOWN |
| FOREST AI VALUE | Highest. Contains approved geometry (stands, cutting areas, restrictions) against which all independent evidence is compared |
| CONFIDENCE | CONFIRMED (architecture), UNKNOWN (APIs) |
| SOURCE | LAD56 §3, §6, §13 |

Public map `mdps.rigasmezi.lv/map` is CONFIRMED as public (lvportals.lv, lsm.lv). It was **not inspected**: the site's robots.txt disallows automated access, so it was respected. Whether it exposes WMS/WFS/tiles: REQUIRES CLIENT CONFIRMATION.

### 2.2 FOREMS

| Field | Value |
|---|---|
| PURPOSE | Desktop front-end to MDPS |
| VENDOR | UNKNOWN. Not to be confused with **FOREMMS** (EU research project 2000–2002, Norwegian Computing Center), which is unrelated |
| CONFIRMED USE | CONFIRMED at Rīgas meži. Also used by Ingka Investments Latvia |
| DATA AVAILABLE | Same DB as MDPS |
| INTEGRATION OPTIONS | None needed. It is a client of the same database |
| FOREST AI VALUE | None as a separate integration |
| CONFIDENCE | CONFIRMED (role), UNKNOWN (vendor) |
| SOURCE | LAD56 §3 |

### 2.3 Go GIS (SunGIS)

| Field | Value |
|---|---|
| PURPOSE | Web map/browser front-end of MDPS ("MDPS GoGIS") |
| VENDOR | SIA SunGIS (sungis.lv). SunGIS was also a LAD56 partner and built the modelling tool integrated into MDPS |
| CONFIRMED USE | CONFIRMED |
| DATA AVAILABLE | Same DB as MDPS |
| INTEGRATION OPTIONS | SunGIS trains clients in QGIS, GDAL, PostgreSQL, PostGIS and MapServer, so OGC services (WMS/WFS via MapServer) are POSSIBLE. Not confirmed for MDPS |
| FOREST AI VALUE | **Strategic, not technical.** SunGIS is the party that actually maintains MDPS. Any DB view, export or service for Forest AI will most likely be built or approved by them |
| CONFIDENCE | CONFIRMED (role, vendor), POSSIBLE (OGC services) |
| SOURCE | LAD56 §3, §9, §10; sungis.lv |

### 2.4 PostgreSQL / PostGIS

| Field | Value |
|---|---|
| PURPOSE | MDPS central database |
| CONFIRMED USE | **PostgreSQL: CONFIRMED.** **PostGIS: HIGHLY LIKELY, NOT CONFIRMED.** Evidence: the DB stores spatial data and QGIS edits it directly; the vendor works with PostGIS. But LAD56 never names PostGIS |
| INTEGRATION OPTIONS | Read-only role on dedicated views (schema `forest_ai_export`). Technically simplest and most powerful. Politically hardest (§4) |
| FOREST AI VALUE | One connection could cover stands, cutting areas, operations, restrictions and possibly imported harvest volumes |
| CONFIDENCE | PostgreSQL CONFIRMED, PostGIS HIGHLY LIKELY |
| SOURCE | LAD56 §3 |

### 2.5 QGIS

| Field | Value |
|---|---|
| PURPOSE | Professional cartography and direct data editing; prepares data packages for the mobile apps |
| CONFIRMED USE | CONFIRMED, direct connection to central DB |
| INTEGRATION OPTIONS | **Output channel for Forest AI, not an input.** Forest AI can publish a `FOREST_AI_RISKS` layer (GeoPackage, or a table/view in their DB) that RM GIS users open in QGIS |
| FOREST AI VALUE | High for adoption: risks show up in the tool the GIS team already uses |
| CONFIDENCE | CONFIRMED |
| SOURCE | LAD56 §3, §13 |

### 2.6 QField

| Field | Value |
|---|---|
| PURPOSE | Mobile field GIS |
| VENDOR | OPENGIS.ch (QField, QFieldCloud, QFieldSync) |
| CONFIRMED USE | CONFIRMED. Data delivered as GeoPackage. Also used in LAD56 for technological map projects for manual harvesting |
| DATA AVAILABLE | Outbound: map packages. **Inbound field observations (photos, forms, tracks): UNKNOWN.** Whether RM collects anything in QField and how it returns (QFieldCloud / file sync): REQUIRES CLIENT CONFIRMATION |
| INTEGRATION OPTIONS | If RM collects observations: read the returned .gpkg. QFieldCloud use: UNKNOWN |
| FOREST AI VALUE | Medium, and conditional on RM actually collecting field data in it |
| CONFIDENCE | CONFIRMED (use), UNKNOWN (data return) |
| SOURCE | LAD56 §3, §13 |

### 2.7 IntraMaps Roam

| Field | Value |
|---|---|
| PURPOSE | Mobile field GIS |
| CONFIRMED USE | CONFIRMED, fed by GeoPackage outside the central DB |
| INTEGRATION OPTIONS | Same pattern as QField. Server-side API: UNKNOWN |
| FOREST AI VALUE | Medium, conditional on field data collection |
| CONFIDENCE | CONFIRMED (use), UNKNOWN (rest) |
| SOURCE | LAD56 §3 |

**Correction to the original hypothesis:** IntraMaps Roam is not downstream of QGIS. Both QField and Roam consume GeoPackage packages prepared from the central DB, and QGIS is one of the tools that prepares them.

### 2.8 Palma Timber — HIGH PRIORITY

| Field | Value |
|---|---|
| PURPOSE | Harvest planning, work orders to contractors, receiving data from forest machines |
| VENDOR | UNKNOWN. Not found in public sources |
| CONFIRMED USE | CONFIRMED |
| DATA AVAILABLE | Work orders (PDF); technological maps (printed maps in machines); **harvested volumes from machines in StanForD format**, imported into the IS and used for settlement documentation |
| INTEGRATION OPTIONS | (a) Receive copies of **StanForD files** (likely StanForD 2010 `.hpr`/`.prd`, version REQUIRES CLIENT CONFIRMATION). (b) Read imported volumes from MDPS if they land in the central DB. Which of (a)/(b) is true: REQUIRES CLIENT CONFIRMATION. Palma API: UNKNOWN |
| FOREST AI VALUE | **Very high.** Machine production data is independent evidence produced by the contractor's machine, not by the contractor's paperwork. Depending on machine configuration, StanForD production files can carry machine/stem positions, which would allow checking "where was timber actually cut" against the approved cutting area. Whether RM's files contain coordinates: REQUIRES CLIENT CONFIRMATION (one sample file answers it) |
| CONFIDENCE | CONFIRMED (role, StanForD), UNKNOWN (vendor, API) |
| SOURCE | LAD56 §3 |

### 2.9 OIN work orders (MDPS → forest machines)

| Field | Value |
|---|---|
| PURPOSE | Digital harvesting work order with cutting boundaries for the machine computer |
| CONFIRMED USE | CONFIRMED as a capability built in LAD56 and integrated into the MDPS planning environment. Use in day-to-day production: REQUIRES CLIENT CONFIRMATION |
| FOREST AI VALUE | High. This is the **exact approved boundary sent to the machine**, which is the ideal reference geometry for "harvest outside approved area" |
| SOURCE | LAD56 §13, §17; github.com/rigasmezi/oin_project |

### 2.10 Horizon

| Field | Value |
|---|---|
| PURPOSE | Reported as accounting/ERP. **Not mentioned in LAD56** |
| CONFIRMED USE | UNKNOWN |
| FOREST AI VALUE | Low for operational control. Possibly contractor invoices vs. machine volumes later |
| CONFIDENCE | UNKNOWN |

### 2.11 Government and open data

| Source | Relationship | Confidence |
|---|---|---|
| VMD Meža valsts reģistrs | Inventory synced, structure identical | CONFIRMED |
| DAP IS Ozols (biotopes, species sites, ĪADT, micro-reserves) | Data used | CONFIRMED |
| VZD open cadastre data | Data used | CONFIRMED |
| LĢIA Lidar | Data used | CONFIRMED |
| LVMI Silava depth-to-water (from Lidar) | Data used | CONFIRMED |
| VMD "Mednis" app data | Discussed; needs agreement with VMD | CONFIRMED (as discussed, not as active) |
| LAD | Reported in prompt; not in LAD56 | UNKNOWN |

These are mostly **data the client consumes**, not live integrations. Several are open data that Forest AI could fetch itself without RM's involvement.

### 2.12 Satellite

| Source | Status |
|---|---|
| Sentinel-2 in Forest AI | CONNECTED (existing Sentinel Hub integration) |
| Sentinel-2 at Rīgas meži | CONFIRMED, used manually to verify harvest results (LAD56 §17) |

---

## 3. Optional / contractor systems

PONSSE Manager, John Deere TimberManager, Komatsu MaxiFleet, fleet GPS, weighbridge systems, Planet.
**No evidence that Rīgas meži uses any of them.** Forest machines are operated by contractors (e.g. Niedrāji MR in LAD56). Their telematics belong to the contractor, not to RM. Only StanForD files reach RM, through Palma.

---

## 4. Constraints that shape the integration

1. **National-security-significant company status (since 2021).** Expect security review, procurement rules and reluctance to open the DB to an external SaaS on a foreign cloud. A direct inbound DB connection from a DigitalOcean VPS is the option most likely to be refused.
   → Design for **outbound-only, client-controlled** data flow (file export or an on-prem connector that pushes).
2. **Recent merger.** Riga City Council decided to merge Rīgas meži with Rīgas Nacionālais zooloģiskais dārzs. IT ownership and decision-makers may be in flux. REQUIRES CLIENT CONFIRMATION.
3. **SunGIS dependency.** Any DB view or export will likely be implemented by the MDPS vendor. Budget and timeline for that work sit with RM, not with Forest AI.

---

## 5. Client questions (send before any build)

**Access & policy**
1. Who owns MDPS technically: in-house IT, SunGIS, or both? Who approves third-party data access?
2. Given the national-security status: is external SaaS processing of MDPS data allowed? Must data stay in the EU / Latvia / on-prem?
3. Preferred access pattern: (a) scheduled GeoPackage export to a folder or SFTP, (b) read-only DB role on dedicated views, (c) on-prem connector, (d) API through Go GIS?

**MDPS data**
4. Is PostGIS used? Which CRS (LKS-92 / EPSG:3059 assumed, needs confirmation)?
5. Can you export one sample GeoPackage for one mežniecība: stands, cirsmas with status/dates, forestry operations, restrictions (ĪADT, micro-reserves, biotopes), mežniecība boundaries?
6. Do contractor and work order records (who, where, when, status) live in MDPS or only in Palma?

**Palma Timber / machines**
7. Palma vendor and version? Any API or automated export?
8. Which StanForD version and file types (`.hpr`, `.prd`, `.oin`)? Do production files include machine/stem coordinates?
9. Are imported volumes stored in the MDPS central DB (which table/view)?
10. Is the OIN generator used in daily production or only in the LAD56 pilot?

**Field**
11. Do field staff collect observations (photos, damage, forms, tracks) in QField or Roam? How do they return to the office: QFieldCloud, file sync, or manual?
12. Is QFieldCloud used?

**Other**
13. Does `mdps.rigasmezi.lv` expose WMS/WFS/tiles we are allowed to use?
14. What is Horizon used for?
15. Do you want Forest AI risks back inside your GIS (a QGIS layer)? In which format?

---

## 6. Sources

- LAD56 final report (2025): https://laukutikls.lv/wp-content/uploads/2025/07/LAD56_nosleguma_zinojums.pdf
- National-security status, public MDPS map, organization: https://lvportals.lv/dienaskartiba/347192-necert-egli-rigas-mezos-2022
- Public MDPS map for walkers: https://www.lsm.lv/raksts/dzive--stils/valasprieki/izveidota-digitala-karte-pastaigam-rigas-mezos.a385964/
- Go GIS / SunGIS: https://sungis.lv/home
- Rīgas meži GitHub: https://github.com/rigasmezi
- Merger with Riga Zoo, 2026 news list: https://lvportals.lv/arhivs/iestade:8410/kartot:popularakais/no:04.09.2025.
- QField vendor: https://qfield.org/partners.html
