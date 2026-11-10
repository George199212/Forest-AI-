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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")
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
        return rows[:limit]

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
        zone = self.a["_inside"] | self.a["_buffer"]
        if not self._usable(acq):
            return self._record(acq, "NOT_USABLE", details={"valid_pct_inside": acq["valid_pct_inside"],
                                                            "min_valid_pct": self.cfg["min_valid_pct"]})
        n_base = self.cfg["baseline_max_acq"]
        if acq["sensor"] == "S2":
            baseline = self._earlier(acq, acq["sensing_time_utc"], n_base)
            if not baseline:
                return self._record(acq, "NO_BASELINE")
            after = self._layers(acq)
            changed, comparable, d = det.s2_change(after, [self._layers(b) for b in baseline], zone, self.cfg)
            persisted = None
            extra = {"ndmi_drop_pixels": int((d["ndmi_drop"] & changed).sum()),
                     "comparable_pixels": int(comparable.sum())}
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
        results = self._upsert_events(acq, baseline, big, eq, extra)
        outcome = "EVENT_UPDATED" if all(o == "EVENT_UPDATED" for _, o in results) else "EVENT_CREATED"
        self._record(acq, outcome, baseline, det.event_stats(big, self.a["_inside"], self.a["_buffer"],
                                                             self.a["_dist"], self.a["grid"], self.a["area_ha"]),
                     persisted=persisted, event_id=results[0][0],
                     details={**extra, "evidence_quality": eq, "gap_days": gap,
                              "events": [{"event_id": e, "outcome": o} for e, o in results]})

    def _snow_pct(self, acq_id):
        r = self.conn.execute("SELECT mean FROM sat_area_metrics WHERE acquisition_id=? AND metric='SNOW_PCT' "
                              "AND zone='INSIDE'", (acq_id,)).fetchone()
        return r["mean"] if r else None

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
        snow = self._snow_pct(acq["id"]) if acq["sensor"] == "S2" else None
        cls, caveat = det.classify(eq, prov.parse_time(t_after).month, snow, stats["changed_area_ha_buffer"], self.cfg)
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
            np.save(self._mask_path(target["id"]), mask)
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
        p.parent.mkdir(parents=True, exist_ok=True)
        np.save(p, mask)
        self.conn.execute("UPDATE sat_change_events SET change_mask_path=? WHERE id=?", (str(p), eid))
        self.conn.commit()
        return eid, "EVENT_CREATED"


def _prepare_area(a, cfg):
    inside, buffer, dist = geo.masks(a["geometry"], a["grid"], a["buffer_m"])
    a.update(_inside=inside, _buffer=buffer, _dist=dist, _n_inside=int(inside.sum()), _n_buffer=int(buffer.sum()))
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
            area_list = [_prepare_area(a, cfg) for a in areas_mod.active(conn, area_ids)]
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
                    "pu_includes_estimates": r.pu_est, "errors": r.errors}
    finally:
        if own_conn:
            conn.close()
