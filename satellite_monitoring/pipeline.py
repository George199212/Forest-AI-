"""One code path for TIMER, MANUAL and BACKFILL runs.

  lock -> run row -> discovery (ONE Catalog search per sensor over the union bbox)
  -> new products stored PENDING (S2 scene cloud > limit -> SKIPPED_CLOUD, never fetched)
  -> fetch PENDING products (quota guard before every request) -> metrics
  -> change detection on every new OK acquisition (chronological) -> events
Re-running is idempotent: UNIQUE(area, sensor, product_id) for acquisitions and
one sat_detections row per acquisition.
"""
import fcntl
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import areas as areas_mod, cdse, config, context, db as sdb, detection as det, geometry as geo
from . import metrics as met, provider as prov


class GuardStop(Exception):
    pass


class Locked(Exception):
    pass


# ── lock ────────────────────────────────────────────────────────────────────
class RunLock:
    def __init__(self, path):
        self.path = Path(path)
        self.fh = None

    def __enter__(self):
        config.secure_dir(self.path.parent)
        self.fh = open(self.path, "a+")
        config.secure_file(self.path)
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.fh.close()
            raise Locked(str(self.path))
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(json.dumps({"pid": os.getpid(), "since_utc": sdb.iso(sdb.utcnow())}))
        self.fh.flush()
        return self

    def __exit__(self, *exc):
        try:
            self.fh.seek(0)
            self.fh.truncate()
        finally:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()


def lock_path():
    return config.raster_root() / ".sat-monitoring.lock"


def lock_state(path=None):
    path = Path(path or lock_path())
    if not path.exists():
        return {"locked": False}
    with open(path, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh, fcntl.LOCK_UN)
            return {"locked": False}
        except BlockingIOError:
            fh.seek(0)
            try:
                return {"locked": True, **json.loads(fh.read() or "{}")}
            except ValueError:
                return {"locked": True}


# ── runner ──────────────────────────────────────────────────────────────────
class Runner:
    def __init__(self, conn, provider, trigger, cfg=None, decoder=None, now=None, forest_conn=None):
        self.conn = conn
        self.provider = provider
        self.trigger = trigger
        self.cfg = cfg or config.DEFAULTS
        if decoder is None:
            from . import raster
            decoder = raster.decode_tiff
        self.decode = decoder
        self.now = now or sdb.utcnow()
        self.forest_conn = forest_conn
        self.run_id = None
        self.errors = []
        self.requests = 0
        self.pu = 0.0
        self.pu_est = False
        self.new_acq = 0
        target = getattr(provider, "client", provider)
        target.on_request = self._log_request

    # every HTTP request to Sentinel Hub lands here (retries included)
    def _log_request(self, kind, http_status, response):
        pu = None
        if response is not None and http_status == 200 and kind == "PROCESS":
            try:
                pu = float(response.headers.get("x-processingunits-spent"))
            except (TypeError, ValueError, AttributeError):
                pu = None
        self.conn.execute("INSERT INTO sat_request_log (run_id, at_utc, kind, sensor, http_status, pu, pu_is_estimate)"
                          " VALUES (?,?,?,?,?,?,?)",
                          (self.run_id, sdb.iso(sdb.utcnow()), kind, getattr(self, "_sensor", None), http_status,
                           pu, 0 if pu is not None else None))
        self.conn.commit()
        self.requests += 1
        if pu is not None:
            self.pu += pu
        self._last_request_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def _guard(self, pu_needed=0.0):
        u = sdb.month_usage(self.conn, self.now)
        f = self.cfg["guard_stop_fraction"]
        if u["requests"] + 1 > f * self.cfg["monthly_request_budget"]:
            raise GuardStop(f"request guard: {u['requests']} of {self.cfg['monthly_request_budget']} used this month "
                            f"(stop at {int(f * 100)}%)")
        if u["pu"] + pu_needed > f * self.cfg["monthly_pu_budget"]:
            raise GuardStop(f"PU guard: {u['pu']:.2f} of {self.cfg['monthly_pu_budget']:.0f} PU used this month "
                            f"(stop at {int(f * 100)}%)")

    # ── phases ──────────────────────────────────────────────────────────────
    def discover(self, area_list, sensors, date_from, date_to):
        for sensor in sensors:
            self._sensor = sensor
            self._guard()
            bbox = geo.union_bbox([a["grid"] for a in area_list])
            try:
                products = self.provider.discover(sensor, bbox, date_from, date_to)
                sdb.provider_status(self.conn, "catalog", True)
            except cdse.CdseError as e:
                sdb.provider_status(self.conn, "catalog", False, str(e))
                self.errors.append({"phase": "discover", "sensor": sensor, "error": str(e)})
                if e.kind in ("NOT_CONFIGURED", "AUTH"):
                    sdb.provider_status(self.conn, "token", False, str(e))
                    raise
                continue
            for a in area_list:
                footprint_area = geo.bbox_polygon(a["grid"]["bbox"])
                n_in, n_buf = a["_n_inside"], a["_n_buffer"]
                for p in products:
                    if p.footprint:
                        import shapely.geometry
                        if not shapely.geometry.shape(p.footprint).intersects(footprint_area):
                            continue
                    self._store_discovered(a, p, n_in, n_buf)

    def _store_discovered(self, a, p, n_in, n_buf):
        skip = (p.sensor == "S2" and p.scene_cloud_pct is not None
                and p.scene_cloud_pct > self.cfg["s2_max_scene_cloud_pct"])
        status = "SKIPPED_CLOUD" if skip else "PENDING"
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO sat_acquisitions (monitored_area_id, sensor, product_id, item_ids_json,"
            " sensing_time_utc, platform, orbit_direction, relative_orbit, scene_cloud_pct, status, attempts,"
            " error_text, discovered_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)",
            (a["id"], p.sensor, p.product_id, sdb.dumps(p.item_ids), p.sensing_time_utc, p.platform,
             p.orbit_direction, p.relative_orbit, p.scene_cloud_pct, status,
             f"scene cloud {p.scene_cloud_pct:.1f}% > {self.cfg['s2_max_scene_cloud_pct']}%" if skip else None,
             self.run_id))
        if cur.rowcount:
            self.new_acq += 1
            if skip:
                self._write_metrics(cur.lastrowid, met.null_metric_rows(
                    p.sensor, f"SKIPPED_CLOUD (scene {p.scene_cloud_pct:.1f}%)", n_in, n_buf))
        self.conn.commit()

    def _write_metrics(self, acq_id, rows):
        for metric, zone, s in rows:
            self.conn.execute(
                "INSERT OR REPLACE INTO sat_area_metrics (acquisition_id, metric, zone, mean, median, p10, p90,"
                " n_valid_pixels, n_total_pixels, null_reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (acq_id, metric, zone, s["mean"], s["median"], s["p10"], s["p90"], s["n_valid_pixels"],
                 s["n_total_pixels"], s["null_reason"]))

    def _priority(self, area_list):
        """Areas with open suspected events first, then the longest without a valid S2."""
        def key(a):
            open_ev = self.conn.execute("SELECT COUNT(*) FROM sat_change_events WHERE monitored_area_id=? "
                                        "AND status IN ('SUSPECTED','FIELD_CHECK_REQUESTED')", (a["id"],)).fetchone()[0]
            last = self.conn.execute("SELECT MAX(sensing_time_utc) FROM sat_acquisitions WHERE monitored_area_id=? "
                                     "AND sensor='S2' AND status='OK' AND valid_pct_inside>=?",
                                     (a["id"], self.cfg["min_valid_pct"])).fetchone()[0]
            return (-open_ev, last or "")
        return sorted(area_list, key=key)

    def fetch(self, area_list, sensors):
        from . import raster
        for a in self._priority(area_list):
            pending = self.conn.execute(
                "SELECT * FROM sat_acquisitions WHERE monitored_area_id=? AND status='PENDING' AND attempts<? "
                f"AND sensor IN ({','.join('?' * len(sensors))}) ORDER BY sensing_time_utc",
                (a["id"], self.cfg["max_attempts"], *sensors)).fetchall()
            for row in pending:
                self._sensor = row["sensor"]
                p = prov.Product(row["sensor"], row["product_id"], row["sensing_time_utc"], row["platform"],
                                 row["orbit_direction"], row["relative_orbit"], row["scene_cloud_pct"])
                est = prov.estimate_pu(row["sensor"], a["grid"]["width"], a["grid"]["height"], self.cfg)
                self._guard(est)
                self._last_request_id = None
                try:
                    res = self.provider.fetch_area_raster(row["sensor"], p, a["grid"])
                    sdb.provider_status(self.conn, "process", True)
                    bands = 6 if row["sensor"] == "S2" else 3
                    arr = self.decode(res.raw, expected_shape=(a["grid"]["height"], a["grid"]["width"]), bands=bands)
                except cdse.CdseError as e:
                    if e.kind in ("NOT_CONFIGURED", "AUTH"):
                        sdb.provider_status(self.conn, "token", False, str(e))
                        raise                         # not the product's fault: attempts unchanged
                    sdb.provider_status(self.conn, "process", False, str(e))
                    self._fail(row, a, str(e))
                    continue
                except Exception as e:                # decode / shape problems
                    self._fail(row, a, f"{type(e).__name__}: {str(e)[:200]}")
                    continue
                if res.pu_is_estimate and self._last_request_id:
                    self.conn.execute("UPDATE sat_request_log SET pu=?, pu_is_estimate=1 WHERE id=?",
                                      (res.pu_spent, self._last_request_id))
                    self.pu += res.pu_spent
                    self.pu_est = True
                self._store_fetched(row, a, arr, res)

    def _fail(self, row, a, msg):
        attempts = row["attempts"] + 1
        final = attempts >= self.cfg["max_attempts"]
        self.conn.execute("UPDATE sat_acquisitions SET attempts=?, error_text=?, status=? WHERE id=?",
                          (attempts, msg[:500], "ERROR" if final else "PENDING", row["id"]))
        if final:
            self._write_metrics(row["id"], met.null_metric_rows(row["sensor"], f"FETCH_ERROR after {attempts} attempts",
                                                                a["_n_inside"], a["_n_buffer"]))
        self.conn.commit()
        self.errors.append({"phase": "fetch", "acquisition_id": row["id"], "error": msg[:300], "final": final})

    def _store_fetched(self, row, a, arr, res):
        from . import raster
        layers = met.s2_layers(arr, self.cfg) if row["sensor"] == "S2" else met.s1_layers(arr)
        inside, buffer = a["_inside"], a["_buffer"]
        tif, png = raster.raster_paths(a["id"], row["sensor"], row["sensing_time_utc"], row["product_id"])
        tif_sha = raster.write_file(tif, res.raw)                                      # RAW, unmodified
        png_sha = raster.write_file(png, raster.quicklook_png(row["sensor"], arr, layers["valid"]))
        vp_in = met.valid_pct(layers["valid"], inside)
        vp_buf = met.valid_pct(layers["valid"], buffer)
        self._write_metrics(row["id"], met.metric_rows(row["sensor"], layers, inside, buffer))
        status = "OK" if (layers["valid"] & (inside | buffer)).any() else "NO_VALID_PIXELS"
        self.conn.execute(
            "UPDATE sat_acquisitions SET processing_params_json=?, fetched_at_utc=?, attempts=?, error_text=NULL,"
            " raster_path=?, raster_sha256=?, quicklook_path=?, quicklook_sha256=?, valid_pct_inside=?,"
            " valid_pct_buffer=?, pu_spent=?, pu_is_estimate=?, status=? WHERE id=?",
            (sdb.dumps(res.params), sdb.iso(sdb.utcnow()), row["attempts"] + 1, str(tif), tif_sha, str(png), png_sha,
             vp_in, vp_buf, res.pu_spent, 1 if res.pu_is_estimate else 0, status, row["id"]))
        self.conn.commit()

    # ── detection ───────────────────────────────────────────────────────────
    def detect(self, area_list, sensors):
        # Both sensors in ONE chronological pass, so an S1 and an S2 detection of the
        # same change meet in the same event regardless of which sensor came first.
        for a in area_list:
            if a.get("_forest_error"):
                # F3: no forest mask -> the area is NOT analysed (never silently "all pixels").
                self.errors.append({"phase": "detect", "area_id": a["id"],
                                    "error": f"forest mask unavailable: {a['_forest_error']}"})
                continue
            rows = self.conn.execute(
                "SELECT a.* FROM sat_acquisitions a LEFT JOIN sat_detections d ON d.acquisition_id=a.id "
                f"WHERE a.monitored_area_id=? AND a.sensor IN ({','.join('?' * len(sensors))}) AND a.status='OK' "
                "AND d.acquisition_id IS NULL ORDER BY a.sensing_time_utc, a.sensor", (a["id"], *sensors)).fetchall()
            for r in rows:
                try:
                    Detector(self, a).run(dict(r))
                except Exception as e:
                    self.errors.append({"phase": "detect", "acquisition_id": r["id"],
                                        "error": f"{type(e).__name__}: {str(e)[:200]}"})


class Detector:
    def __init__(self, runner, area):
        self.r = runner
        self.conn = runner.conn
        self.cfg = runner.cfg
        self.a = area
        # F3: analysed pixels = INSIDE + BUFFER, restricted to VMD forest when the forest mask is on.
        self.zone = area.get("_zone")
        if self.zone is None:
            self.zone = area["_inside"] | area["_buffer"]

    def _layers(self, acq):
        from . import raster
        raw = Path(acq["raster_path"]).read_bytes()
        if raster.sha256_bytes(raw) != acq["raster_sha256"]:
            raise ValueError(f"raster sha256 mismatch for acquisition {acq['id']}")
        bands = 6 if acq["sensor"] == "S2" else 3
        arr = self.r.decode(raw, expected_shape=(self.a["grid"]["height"], self.a["grid"]["width"]), bands=bands)
        return met.s2_layers(arr, self.cfg) if acq["sensor"] == "S2" else met.s1_layers(arr)

    def _usable(self, acq):
        return acq["valid_pct_inside"] is not None and acq["valid_pct_inside"] >= self.cfg["min_valid_pct"]

    def _earlier(self, acq, before_time, limit):
        t = prov.parse_time(before_time)
        since = (t - timedelta(days=self.cfg["baseline_max_age_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = self.conn.execute(
            "SELECT * FROM sat_acquisitions WHERE monitored_area_id=? AND sensor=? AND status='OK' "
            "AND valid_pct_inside>=? AND sensing_time_utc<? AND sensing_time_utc>=? ORDER BY sensing_time_utc DESC",
            (self.a["id"], acq["sensor"], self.cfg["min_valid_pct"], before_time, since)).fetchall()
        rows = [dict(x) for x in rows]
        if acq["sensor"] == "S1":
            rows = [x for x in rows if det.same_geometry(x, acq)]
        else:
            excluded = self._excluded_s2()
            rows = [x for x in rows if x["id"] not in excluded]
        return rows[:limit]

    # F: S2 acquisitions never used as baseline (or "after")
    EXCLUDED_OUTCOMES = ("NOT_USABLE", "UNIFORM_DROP_ATMOSPHERIC")

    def _excluded_s2(self):
        ids = {r[0] for r in self.conn.execute(
            f"SELECT acquisition_id FROM sat_detections WHERE monitored_area_id=? AND sensor='S2' "
            f"AND outcome IN ({','.join('?' * len(self.EXCLUDED_OUTCOMES))})", (self.a["id"], *self.EXCLUDED_OUTCOMES))}
        ids |= {r[0] for r in self.conn.execute(
            "SELECT acquisition_id FROM sat_s2_candidates WHERE monitored_area_id=? "
            "AND status IN ('PENDING_CONFIRMATION','TRANSIENT')", (self.a["id"],))}
        return ids

    def _record(self, acq, outcome, baseline=None, stats=None, persisted=None, event_id=None, details=None):
        stats = stats or {}
        self.conn.execute(
            "INSERT OR REPLACE INTO sat_detections (acquisition_id, monitored_area_id, sensor, ran_at_utc, outcome,"
            " baseline_acq_ids, n_changed_pixels, changed_area_ha, largest_cluster_ha, persisted, event_id,"
            " details_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (acq["id"], self.a["id"], acq["sensor"], sdb.iso(sdb.utcnow()), outcome,
             sdb.dumps([b["id"] for b in baseline]) if baseline is not None else None,
             stats.get("n_changed_pixels"), stats.get("changed_area_ha"), stats.get("largest_cluster_ha"),
             persisted, event_id, sdb.dumps(details) if details else None))
        self.conn.commit()

    def run(self, acq):
        zone = self.zone
        if not self._usable(acq):
            return self._record(acq, "NOT_USABLE", details={"valid_pct_inside": acq["valid_pct_inside"],
                                                            "min_valid_pct": self.cfg["min_valid_pct"]})
        n_base = self.cfg["baseline_max_acq"]
        if acq["sensor"] == "S2":
            return self._run_s2(acq, zone, n_base)
        else:
            if acq["relative_orbit"] is None or acq["orbit_direction"] is None:
                return self._record(acq, "NOT_USABLE", details={"reason": "unknown orbit geometry; never compared"})
            earlier = self._earlier(acq, acq["sensing_time_utc"], n_base + 1)
            if not earlier:
                return self._record(acq, "NO_BASELINE")
            after = self._layers(acq)
            prev = earlier[0]
            baseline = self._earlier(acq, prev["sensing_time_utc"], n_base)
            if baseline:
                bl = [self._layers(b)["VH_LIN"] for b in baseline]
                drop_a, comparable, _ = det.s1_drop(after["VH_LIN"], bl, zone, self.cfg)
                drop_p, _, _ = det.s1_drop(self._layers(prev)["VH_LIN"], bl, zone, self.cfg)
                persistent = drop_a & drop_p
            else:                                   # only one earlier image: a drop can only be single
                baseline = earlier[:n_base]
                drop_a, comparable, _ = det.s1_drop(after["VH_LIN"], [self._layers(b)["VH_LIN"] for b in baseline],
                                                    zone, self.cfg)
                persistent = np.zeros_like(drop_a)
            big_persist = det.keep_large_clusters(persistent, self.a["grid"], self.cfg["min_cluster_ha"])
            if not big_persist.any():
                big_single = det.keep_large_clusters(drop_a, self.a["grid"], self.cfg["min_cluster_ha"])
                stats = det.event_stats(drop_a, self.a["_inside"], self.a["_buffer"], self.a["_dist"],
                                        self.a["grid"], self.a["area_ha"])
                outcome = "SINGLE_DROP" if big_single.any() else ("NO_CHANGE" if not drop_a.any() else "CANDIDATE_BELOW_MIN")
                return self._record(acq, outcome, baseline, stats, persisted=0,
                                    details={"previous_same_geometry_acq": prev["id"],
                                             "note": "radar-only drop stored as observation; needs persistence"}
                                    if outcome == "SINGLE_DROP" else None)
            changed, persisted = persistent, 1
            extra = {"previous_same_geometry_acq": prev["id"], "comparable_pixels": int(comparable.sum())}

        stats_all = det.event_stats(changed, self.a["_inside"], self.a["_buffer"], self.a["_dist"],
                                    self.a["grid"], self.a["area_ha"])
        big = det.keep_large_clusters(changed, self.a["grid"], self.cfg["min_cluster_ha"])
        if not big.any():
            outcome = "NO_CHANGE" if not changed.any() else "CANDIDATE_BELOW_MIN"
            return self._record(acq, outcome, baseline, stats_all, persisted=persisted, details=extra)
        gap = (prov.parse_time(acq["sensing_time_utc"]) - prov.parse_time(baseline[0]["sensing_time_utc"])).days
        eq = det.evidence_quality(acq["valid_pct_inside"], len(baseline), gap, self.cfg)
        stats_big = det.event_stats(big, self.a["_inside"], self.a["_buffer"], self.a["_dist"], self.a["grid"],
                                    self.a["area_ha"])
        # S1-only persistent drop -> RADAR_ANOMALY (timeline only). Promoted to an event only by rule a/b.
        aid = self._create_radar_anomaly(acq, baseline, extra["previous_same_geometry_acq"], big, eq,
                                         {**extra, "gap_days": gap})
        results, rule = self._promote_radar(aid)
        details = {**extra, "evidence_quality": eq, "gap_days": gap, "radar_anomaly_id": aid}
        if not results:
            return self._record(acq, "RADAR_ANOMALY", baseline, stats_big, persisted=persisted,
                                details={**details, "note": "S1-only persistent drop; not an event unless promoted"})
        outcome = "EVENT_UPDATED" if all(o == "EVENT_UPDATED" for _, o in results) else "EVENT_CREATED"
        self._record(acq, outcome, baseline, stats_big, persisted=persisted, event_id=results[0][0],
                     details={**details, "promotion_rule": rule,
                              "events": [{"event_id": e, "outcome": o} for e, o in results]})

    # ── S1 radar anomalies (S1-only persistent drops) ────────────────────────
    def _radar_mask_path(self, aid):
        return config.raster_root() / str(self.a["id"]) / "radar_anomalies" / f"anomaly_{aid}_mask.npy"

    def _create_radar_anomaly(self, acq, baseline, prev_id, mask, eq, details):
        stats = det.event_stats(mask, self.a["_inside"], self.a["_buffer"], self.a["_dist"], self.a["grid"],
                                self.a["area_ha"])
        cur = self.conn.execute(
            "INSERT INTO sat_radar_anomalies (monitored_area_id, acquisition_id, sensing_time_utc, orbit_direction,"
            " relative_orbit, baseline_acq_ids, previous_acq_id, created_at_utc, mask_path, n_pixels, changed_area_ha,"
            " evidence_quality, details_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.a["id"], acq["id"], acq["sensing_time_utc"], acq["orbit_direction"], acq["relative_orbit"],
             sdb.dumps([b["id"] for b in baseline]), prev_id, sdb.iso(sdb.utcnow()), "", stats["n_changed_pixels"],
             stats["changed_area_ha"], eq, sdb.dumps(details)))
        aid = cur.lastrowid
        p = self._radar_mask_path(aid)
        self._save_mask(p, mask)
        self.conn.execute("UPDATE sat_radar_anomalies SET mask_path=? WHERE id=?", (str(p), aid))
        self.conn.commit()
        return aid

    def _anomaly(self, aid):
        an = dict(self.conn.execute("SELECT * FROM sat_radar_anomalies WHERE id=?", (aid,)).fetchone())
        acq = dict(self.conn.execute("SELECT * FROM sat_acquisitions WHERE id=?", (an["acquisition_id"],)).fetchone())
        base = [dict(self.conn.execute("SELECT * FROM sat_acquisitions WHERE id=?", (i,)).fetchone())
                for i in json.loads(an["baseline_acq_ids"])]
        return an, acq, base, np.load(an["mask_path"]).astype(bool)

    def _mark_promoted(self, aid, rule, event_id):
        self.conn.execute("UPDATE sat_radar_anomalies SET status='PROMOTED', promotion_rule=?, promoted_at_utc=?,"
                          " event_id=? WHERE id=? AND status='RADAR_ANOMALY'",
                          (rule, sdb.iso(sdb.utcnow()), event_id, aid))
        self.conn.commit()

    def _attach_to_events(self, aid, s2_only):
        """Rule a (and continuation of an already promoted S1 event): clusters of the anomaly that overlap an
        open event are added to it. s2_only=True: only events with an S2 after-image within
        s1_anomaly_s2_confirm_days of the anomaly. Returns [(event_id, outcome)]."""
        an, acq, base, mask = self._anomaly(aid)
        t = prov.parse_time(an["sensing_time_utc"])
        days = self.cfg["s1_anomaly_s2_confirm_days"]
        ongoing = timedelta(days=self.cfg["ongoing_max_gap_days"])
        labels, sizes = det.clusters(mask, self.a["grid"]["pixel_area_ha"])
        out = []
        for ev in self.conn.execute("SELECT * FROM sat_change_events WHERE monitored_area_id=? AND status IN "
                                    "('SUSPECTED','FIELD_CHECK_REQUESTED') ORDER BY id", (self.a["id"],)).fetchall():
            ev = dict(ev)
            hist = json.loads(ev["after_acq_history_json"])
            s2_times = [prov.parse_time(h["time"]) for h in hist if h["sensor"] == "S2"]
            if s2_times:
                ok = any(abs((x - t).days) <= days for x in s2_times)
            else:                                    # S1-only event: exists only via rule b
                ok = (not s2_only and prov.parse_time(ev["first_after_time_utc"]) - ongoing <= t
                      <= prov.parse_time(ev["last_after_time_utc"]) + ongoing)
            if not ok:
                continue
            old = np.load(ev["change_mask_path"]).astype(bool)
            grown = det.dilate1(old)
            m = np.zeros_like(mask)
            for k in range(1, sizes.size + 1):
                cm = labels == k
                if det.overlap_fraction(cm, grown) >= self.cfg["ongoing_overlap_fraction"]:
                    m |= cm
            if m.any():
                out.append(self._apply_event(acq, base, m, an["evidence_quality"], ev, old))
        return out

    def _persistent_multi_orbit_mask(self, t_iso):
        """Rule b: pixels changed in >= s1_promote_min_acq anomalies from >= s1_promote_min_orbits geometries
        within s1_promote_window_days before t, as clusters >= s1_promote_min_ha."""
        since = (prov.parse_time(t_iso) - timedelta(days=self.cfg["s1_promote_window_days"])).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM sat_radar_anomalies WHERE monitored_area_id=? AND sensing_time_utc>=? AND sensing_time_utc<=?"
            " ORDER BY sensing_time_utc", (self.a["id"], since, t_iso))]
        if len(rows) < self.cfg["s1_promote_min_acq"]:
            return None, []
        masks = [np.load(r["mask_path"]).astype(bool) for r in rows]
        count = np.sum(masks, axis=0)
        per_orbit = {}
        for r, m in zip(rows, masks):
            # F3: DISTINCT relative orbits (S1A/S1C/S1D share the track numbering, so two platforms on the
            # same relative orbit count once).
            k = r["relative_orbit"]
            per_orbit[k] = per_orbit.get(k, np.zeros_like(m)) | m
        n_orbits = np.sum(list(per_orbit.values()), axis=0)
        ok = (count >= self.cfg["s1_promote_min_acq"]) & (n_orbits >= self.cfg["s1_promote_min_orbits"])
        ok &= self.zone
        keep = det.keep_large_clusters(ok, self.a["grid"], self.cfg["s1_promote_min_ha"])
        if not keep.any():
            return None, []
        return keep, [r for r, m in zip(rows, masks) if (m & keep).any()]

    def _promote_radar(self, aid):
        """Returns ([(event_id, outcome)], rule) or ([], None) when the anomaly stays an anomaly."""
        res = self._attach_to_events(aid, s2_only=False)
        if res:
            ev = self.conn.execute("SELECT sensor_basis FROM sat_change_events WHERE id=?", (res[0][0],)).fetchone()
            rule = "S2_CONFIRMED" if "S2" in ev[0] else "S1_PERSISTENT_MULTI_ORBIT"
            self._mark_promoted(aid, rule, res[0][0])
            return res, rule
        an = self.conn.execute("SELECT sensing_time_utc FROM sat_radar_anomalies WHERE id=?", (aid,)).fetchone()
        keep, contrib = self._persistent_multi_orbit_mask(an[0])
        if keep is None:
            return [], None
        # F1 (2026-11-11): contributors already PROMOTED are in an event already -> skipped. Every remaining
        # contributor (oldest first) goes through _upsert_events, i.e. each cluster of the rule-b mask is first
        # matched against the open events by mask overlap; only unmatched clusters start a new event. The first
        # contributor may create the event, the following ones then match it (no duplicate masks).
        results = []
        for r in contrib:
            if r["status"] != "RADAR_ANOMALY":
                continue
            _, acq, base, _ = self._anomaly(r["id"])
            res = self._upsert_events(acq, base, keep, r["evidence_quality"], {})
            self._mark_promoted(r["id"], "S1_PERSISTENT_MULTI_ORBIT", res[0][0])
            if r["id"] == aid:
                results = res
        # The new anomaly itself may not overlap the rule-b mask: it then stays an anomaly ([]), even though
        # older contributors were promoted above.
        return (results, "S1_PERSISTENT_MULTI_ORBIT") if results else ([], None)

    def _attach_anomalies_after_s2(self):
        """Rule a, other direction: an S2-confirmed event promotes earlier/later radar anomalies that overlap it
        within s1_anomaly_s2_confirm_days."""
        for (aid,) in self.conn.execute("SELECT id FROM sat_radar_anomalies WHERE monitored_area_id=? AND "
                                        "status='RADAR_ANOMALY' ORDER BY sensing_time_utc", (self.a["id"],)).fetchall():
            res = self._attach_to_events(aid, s2_only=True)
            if res:
                self._mark_promoted(aid, "S2_CONFIRMED", res[0][0])

    # ── S2 (A, B, F, G) ──────────────────────────────────────────────────────
    def _run_s2(self, acq, zone, n_base):
        after = self._layers(acq)                       # validity includes the grown cloud mask (A)
        vp = met.valid_pct(after["valid"], self.a["_inside"])
        details = {"valid_pct_inside_after_cloud_dilation": vp, "valid_pct_inside_stored": acq["valid_pct_inside"],
                   "s2_cloud_dilate_px": self.cfg.get("s2_cloud_dilate_px")}
        if vp is None or vp < self.cfg["min_valid_pct"]:
            return self._record(acq, "NOT_USABLE", details={**details, "min_valid_pct": self.cfg["min_valid_pct"]})
        baseline = self._earlier(acq, acq["sensing_time_utc"], n_base)
        changed = comparable = d = None
        if baseline:
            changed, comparable, d = det.s2_change(after, [self._layers(b) for b in baseline], zone, self.cfg)
            u = det.uniform_drop(changed, comparable, d, self.cfg)
            details["uniform_drop"] = u
            if u["is_uniform"]:                         # G -> F: never baseline, never "after"
                details.update(classification="POSSIBLE_SEASONAL_OR_ENVIRONMENTAL",
                               reason="uniform drop over most of the area (atmospheric/illumination), not a local change")
                stats = det.event_stats(changed, self.a["_inside"], self.a["_buffer"], self.a["_dist"],
                                        self.a["grid"], self.a["area_ha"])
                return self._record(acq, "UNIFORM_DROP_ATMOSPHERIC", baseline, stats, details=details)
        resolved = self._resolve_candidates(acq, after, vp)
        if resolved:
            details["resolved_candidates"] = resolved
        if not baseline:
            return self._record(acq, "NO_BASELINE", details=details)
        details.update(ndmi_drop_pixels=int((d["ndmi_drop"] & changed).sum()), comparable_pixels=int(comparable.sum()))
        stats_all = det.event_stats(changed, self.a["_inside"], self.a["_buffer"], self.a["_dist"],
                                    self.a["grid"], self.a["area_ha"])
        big = det.keep_large_clusters(changed, self.a["grid"], self.cfg["min_cluster_ha"])
        if not big.any():
            return self._record(acq, "NO_CHANGE" if not changed.any() else "CANDIDATE_BELOW_MIN", baseline,
                                stats_all, details=details)
        gap = (prov.parse_time(acq["sensing_time_utc"]) - prov.parse_time(baseline[0]["sensing_time_utc"])).days
        eq = det.evidence_quality(vp, len(baseline), gap, self.cfg)
        cid = self._create_candidate(acq, baseline, big, eq, {"gap_days": gap, **{k: details[k] for k in
                                                              ("valid_pct_inside_after_cloud_dilation", "uniform_drop")}})
        details.update(candidate_id=cid, evidence_quality=eq, gap_days=gap)
        self._record(acq, "PENDING_CONFIRMATION", baseline,
                     det.event_stats(big, self.a["_inside"], self.a["_buffer"], self.a["_dist"], self.a["grid"],
                                     self.a["area_ha"]), details=details)

    def _cand_mask_path(self, cid):
        return config.raster_root() / str(self.a["id"]) / "candidates" / f"candidate_{cid}_mask.npy"

    def _create_candidate(self, acq, baseline, mask, eq, details):
        stats = det.event_stats(mask, self.a["_inside"], self.a["_buffer"], self.a["_dist"], self.a["grid"],
                                self.a["area_ha"])
        cur = self.conn.execute(
            "INSERT INTO sat_s2_candidates (monitored_area_id, acquisition_id, baseline_acq_ids, created_at_utc,"
            " mask_path, n_pixels, changed_area_ha, evidence_quality, details_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (self.a["id"], acq["id"], sdb.dumps([b["id"] for b in baseline]), sdb.iso(sdb.utcnow()), "",
             stats["n_changed_pixels"], stats["changed_area_ha"], eq, sdb.dumps({**details, "stats": stats})))
        cid = cur.lastrowid
        p = self._cand_mask_path(cid)
        self._save_mask(p, mask)
        self.conn.execute("UPDATE sat_s2_candidates SET mask_path=? WHERE id=?", (str(p), cid))
        self.conn.commit()
        return cid

    def _resolve_candidates(self, acq, after, vp):
        """B: the first usable S2 after a candidate decides it, against the candidate's own baseline,
        on the candidate's pixels only."""
        out = []
        t = acq["sensing_time_utc"]
        for c in [dict(x) for x in self.conn.execute(
                "SELECT c.*, a.sensing_time_utc AS cand_time FROM sat_s2_candidates c JOIN sat_acquisitions a "
                "ON a.id=c.acquisition_id WHERE c.monitored_area_id=? AND c.status='PENDING_CONFIRMATION' "
                "ORDER BY c.id", (self.a["id"],))]:
            if c["cand_time"] >= t:
                continue
            cmask = np.load(c["mask_path"]).astype(bool)
            base = [dict(self.conn.execute("SELECT * FROM sat_acquisitions WHERE id=?", (i,)).fetchone())
                    for i in json.loads(c["baseline_acq_ids"])]
            ch, comp, d = det.s2_change(after, [self._layers(b) for b in base], cmask, self.cfg)
            n, nc = int(cmask.sum()), int(comp.sum())
            rec = {"candidate_id": c["id"], "candidate_pixels": n, "comparable_pixels": nc,
                   "comparable_fraction": round(nc / n, 4) if n else None}
            if not n or nc / n < self.cfg["candidate_min_comparable_fraction"]:
                rec["decision"] = "STILL_PENDING"
                out.append(rec)
                continue
            still = ch & cmask
            persist = int(still.sum()) / nc
            keep = det.keep_large_clusters(still, self.a["grid"], self.cfg["min_cluster_ha"])
            med = {k: round(float(np.nanmedian(d[k][comp])), 4) for k in ("dNDVI", "dNBR", "dNDMI")}
            rec.update(persist_fraction=round(persist, 4), median_deltas_on_candidate=med)
            status, event_id = "TRANSIENT", None
            if persist >= self.cfg["candidate_persist_fraction"] and keep.any():
                status = "CONFIRMED"
                orig = dict(self.conn.execute("SELECT * FROM sat_acquisitions WHERE id=?",
                                              (c["acquisition_id"],)).fetchone())
                extra = {"confirmed_candidate_id": c["id"]}
                event_id = self._upsert_events(orig, base, keep, c["evidence_quality"], extra)[0][0]
                gap = (prov.parse_time(t) - prov.parse_time(base[0]["sensing_time_utc"])).days
                self._upsert_events(acq, base, keep, det.evidence_quality(vp, len(base), gap, self.cfg), extra)
                self._attach_anomalies_after_s2()
            rec.update(decision=status, event_id=event_id)
            self.conn.execute("UPDATE sat_s2_candidates SET status=?, resolved_by_acq_id=?, resolved_at_utc=?, "
                              "event_id=?, details_json=? WHERE id=?",
                              (status, acq["id"], sdb.iso(sdb.utcnow()), event_id,
                               sdb.dumps({**json.loads(c["details_json"] or "{}"), "resolution": rec}), c["id"]))
            self.conn.commit()
            out.append(rec)
        return out

    def _snow_pct(self, acq_id):
        r = self.conn.execute("SELECT mean FROM sat_area_metrics WHERE acquisition_id=? AND metric='SNOW_PCT' "
                              "AND zone='INSIDE'", (acq_id,)).fetchone()
        return r["mean"] if r else None

    @staticmethod
    def _save_mask(path, mask):
        config.secure_dir(path.parent)
        np.save(path, mask)
        config.secure_file(path)

    def _mask_path(self, event_id):
        return config.raster_root() / str(self.a["id"]) / "events" / f"event_{event_id}_mask.npy"

    def _geojson(self, mask):
        feats = []
        for zone_name, zone in (("INSIDE", self.a["_inside"]), ("BUFFER", self.a["_buffer"])):
            m = mask & zone
            if m.any():
                f = geo.mask_to_geojson(m, self.a["grid"], {"zone": zone_name,
                                                            "area_ha": round(int(m.sum()) * self.a["grid"]["pixel_area_ha"], 4)})
                if f:
                    feats.append(f)
        return {"type": "FeatureCollection", "features": feats}

    def _upsert_events(self, acq, baseline, mask, eq, extra):
        """Each 8-connected cluster is matched on its own to an open event (overlap
        >= 30 % with the event mask grown by one pixel, within 60 days of its
        after-window). Matched clusters update that event; all unmatched clusters
        together form ONE new event. Returns [(event_id, outcome)]."""
        t = prov.parse_time(acq["sensing_time_utc"])
        gap = timedelta(days=self.cfg["ongoing_max_gap_days"])
        candidates = []
        for ev in self.conn.execute(
                "SELECT * FROM sat_change_events WHERE monitored_area_id=? AND status IN ('SUSPECTED','FIELD_CHECK_REQUESTED')"
                " ORDER BY id DESC", (self.a["id"],)).fetchall():
            if prov.parse_time(ev["first_after_time_utc"]) - gap <= t <= prov.parse_time(ev["last_after_time_utc"]) + gap:
                old = np.load(ev["change_mask_path"])
                candidates.append((dict(ev), old, det.dilate1(old)))
        labels, sizes = det.clusters(mask, self.a["grid"]["pixel_area_ha"])
        groups = {}
        for k in range(1, sizes.size + 1):
            cm = labels == k
            key = None
            for ev, old, grown in candidates:
                if det.overlap_fraction(cm, grown) >= self.cfg["ongoing_overlap_fraction"]:
                    key = ev["id"]
                    break
            groups[key] = groups.get(key, np.zeros_like(mask)) | cm
        by_id = {ev["id"]: (ev, old) for ev, old, _ in candidates}
        out = []
        for key, m in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
            target, old_mask = by_id.get(key, (None, None))
            out.append(self._apply_event(acq, baseline, m, eq, target, old_mask))
        return out

    def _apply_event(self, acq, baseline, mask, eq, target, old_mask):
        t_after = acq["sensing_time_utc"]
        now = sdb.iso(sdb.utcnow())
        before_ids = [b["id"] for b in baseline]
        if target:
            mask = mask | old_mask
            history = json.loads(target["after_acq_history_json"])
            if acq["id"] not in [h["acq_id"] for h in history]:
                history.append({"acq_id": acq["id"], "sensor": acq["sensor"], "time": t_after, "evidence_quality": eq})
            before_ids = sorted(set(json.loads(target["before_acq_ids"])) | set(before_ids))
            eq = max([h["evidence_quality"] for h in history], key=lambda q: det.EQ_ORDER[q])
        else:
            history = [{"acq_id": acq["id"], "sensor": acq["sensor"], "time": t_after, "evidence_quality": eq}]
        sensors = {h["sensor"] for h in history}
        basis = "S1+S2" if sensors == {"S1", "S2"} else next(iter(sensors))
        conf = det.confidence({s: [h["time"] for h in history if h["sensor"] == s] for s in ("S1", "S2")})
        stats = det.event_stats(mask, self.a["_inside"], self.a["_buffer"], self.a["_dist"], self.a["grid"], self.a["area_ha"])
        # F2 (2026-11-11): the class is decided on the ONSET (first after-image) month; the latest after-image
        # only adds a caveat (seasonal_caveat), it never re-classifies an event that started in summer.
        onset = min(history, key=lambda h: h["time"])
        latest = max(history, key=lambda h: h["time"])
        snow_on = self._snow_pct(onset["acq_id"]) if onset["sensor"] == "S2" else None
        cls, cav_on = det.classify(eq, prov.parse_time(onset["time"]).month, snow_on,
                                   stats["changed_area_ha_buffer"], self.cfg)
        caveat = cav_on
        if latest["acq_id"] != onset["acq_id"]:
            snow_last = self._snow_pct(latest["acq_id"]) if latest["sensor"] == "S2" else None
            _, cav_last = det.classify(eq, prov.parse_time(latest["time"]).month, snow_last, None, self.cfg)
            if cav_last:
                note = f"Latest after-image {latest['time'][:10]} (not used for the class): {cav_last}"
                caveat = f"{cav_on} | {note}" if cav_on else note
        before_times = [r["sensing_time_utc"] for r in self.conn.execute(
            f"SELECT sensing_time_utc FROM sat_acquisitions WHERE id IN ({','.join('?' * len(before_ids))})", before_ids)]
        first_after = min(h["time"] for h in history)
        ctx = context.operational_context({"source": self.a["source"], "name": self.a["name"], "geometry": self.a["geometry"]},
                                          min(before_times), max(h["time"] for h in history), self.a["buffer_m"],
                                          forest_conn=self.r.forest_conn)
        values = dict(
            sensor_basis=basis, updated_at_utc=now, before_acq_ids=sdb.dumps(before_ids), after_acq_id=acq["id"],
            after_acq_history_json=sdb.dumps(history), first_after_time_utc=first_after,
            last_after_time_utc=max(h["time"] for h in history),
            changed_area_ha=stats["changed_area_ha"], changed_area_ha_inside=stats["changed_area_ha_inside"],
            changed_area_ha_buffer=stats["changed_area_ha_buffer"], pct_of_area_affected=stats["pct_of_area_affected"],
            max_distance_outside_boundary_m=stats["max_distance_outside_boundary_m"],
            n_changed_pixels=stats["n_changed_pixels"], largest_cluster_ha=stats["largest_cluster_ha"],
            change_geojson=sdb.dumps(self._geojson(mask)), thresholds_json=sdb.dumps(config.thresholds_snapshot()),
            confidence=conf, evidence_quality=eq, classification=cls, seasonal_caveat=caveat,
            gps_context_json=sdb.dumps(ctx))
        if target:
            self._save_mask(self._mask_path(target["id"]), mask)
            sets = ", ".join(f"{k}=?" for k in values)
            self.conn.execute(f"UPDATE sat_change_events SET {sets} WHERE id=?", (*values.values(), target["id"]))
            self.conn.commit()
            return target["id"], "EVENT_UPDATED"
        values.update(monitored_area_id=self.a["id"], detected_at_utc=now, change_mask_path="", status="SUSPECTED")
        cols = ", ".join(values)
        cur = self.conn.execute(f"INSERT INTO sat_change_events ({cols}) VALUES ({','.join('?' * len(values))})",
                                tuple(values.values()))
        eid = cur.lastrowid
        p = self._mask_path(eid)
        self._save_mask(p, mask)
        self.conn.execute("UPDATE sat_change_events SET change_mask_path=? WHERE id=?", (str(p), eid))
        self.conn.commit()
        return eid, "EVENT_CREATED"


def _prepare_area(a, cfg, conn=None):
    inside, buffer, dist = geo.masks(a["geometry"], a["grid"], a["buffer_m"])
    a.update(_inside=inside, _buffer=buffer, _dist=dist, _n_inside=int(inside.sum()), _n_buffer=int(buffer.sum()),
             _forest=None, _forest_meta=None, _forest_error=None)
    zone = inside | buffer
    if cfg.get("forest_mask"):
        from . import forest_mask
        if conn is None:
            a["_forest_error"] = "no satellite.db connection for the mask cache"
        else:
            try:
                a["_forest"], a["_forest_meta"] = forest_mask.get(conn, a, inside, buffer, cfg)
            except forest_mask.ForestMaskUnavailable as e:
                a["_forest_error"] = str(e)
    a["_zone"] = zone & a["_forest"] if a["_forest"] is not None else zone
    return a


def run(trigger, conn=None, provider=None, area_ids=None, date_from=None, date_to=None, sensors=("S1", "S2"),
        cfg=None, decoder=None, now=None, lock_file=None, forest_conn=None):
    """Returns a summary dict. Raises Locked if another run holds the lock."""
    cfg = cfg or config.DEFAULTS
    if trigger not in ("TIMER", "MANUAL", "BACKFILL"):
        raise ValueError("trigger")
    own_conn = conn is None
    conn = conn or sdb.connect()
    if provider is None:
        provider = prov.SentinelHubProvider(cdse.Client(max_rps=cfg["max_requests_per_second"],
                                                        backoff_base_s=cfg["backoff_base_s"],
                                                        max_retries=cfg["backoff_max_retries"]), cfg)
    now = now or sdb.utcnow()
    if trigger != "BACKFILL" or not (date_from and date_to):
        date_to = date_to or now.strftime("%Y-%m-%d")
        date_from = date_from or (now - timedelta(days=cfg["timer_lookback_days"])).strftime("%Y-%m-%d")
    try:
        with RunLock(lock_file or lock_path()):
            r = Runner(conn, provider, trigger, cfg, decoder, now, forest_conn)
            area_list = [_prepare_area(a, cfg, conn) for a in areas_mod.active(conn, area_ids)]
            cur = conn.execute("INSERT INTO sat_runs (trigger, started_at, status, areas, date_from, date_to, sensors)"
                               " VALUES (?,?,?,?,?,?,?)", (trigger, sdb.iso(sdb.utcnow()), "RUNNING",
                                                          sdb.dumps([a["id"] for a in area_list]), date_from, date_to,
                                                          ",".join(sensors)))
            conn.commit()
            r.run_id = cur.lastrowid
            status, stop = "OK", None
            try:
                if area_list:
                    r.discover(area_list, sensors, date_from, date_to)
                    r.fetch(area_list, sensors)
                    r.detect(area_list, sensors)
            except GuardStop as e:
                status, stop = "STOPPED_BY_GUARD", str(e)
                r.detect(area_list, sensors)          # still analyse what was fetched
            except cdse.CdseError as e:
                status, stop = "FAILED", str(e)
            if status == "OK" and r.errors:
                status = "PARTIAL"
            conn.execute("UPDATE sat_runs SET finished_at=?, status=?, new_acquisitions=?, requests_made=?, pu_spent=?,"
                         " pu_includes_estimates=?, errors_json=?, stop_reason=? WHERE id=?",
                         (sdb.iso(sdb.utcnow()), status, r.new_acq, r.requests, round(r.pu, 4), 1 if r.pu_est else 0,
                          sdb.dumps(r.errors) if r.errors else None, stop, r.run_id))
            conn.commit()
            return {"run_id": r.run_id, "status": status, "stop_reason": stop, "areas": [a["id"] for a in area_list],
                    "new_acquisitions": r.new_acq, "requests": r.requests, "pu": round(r.pu, 4),
                    "pu_includes_estimates": r.pu_est, "errors": r.errors,
                    "forest_mask": {a["id"]: ({k: a["_forest_meta"].get(k) for k in (
                        "source_version", "n_compartments", "pixels_analysed", "non_forest_share_zone")}
                        if a["_forest_meta"] else {"error": a["_forest_error"]}) for a in area_list}}
    finally:
        if own_conn:
            conn.close()
