import sys
import json
import requests
import os
from pathlib import Path
from pydantic import BaseModel
from typing import Optional, List, Any
from fitparse import FitFile
from dotenv import load_dotenv

# Load local .env first, then fallback to shared Garmin Analyzer configuration
load_dotenv()
if not os.getenv("NTFY_TOPIC"):
    GARMIN_ANALYZER_DIR = r"c:\Users\rmelamed\Projects\garmin-analyzer"
    ENV_PATH = os.path.join(GARMIN_ANALYZER_DIR, ".env")
    load_dotenv(ENV_PATH)

# Constants
WALK_CADENCE_MAX = 150

class Metadata(BaseModel):
    Date: str
    Course_ID: str
    Total_Distance_m: float

class SessionMacro(BaseModel):
    Avg_Pace_min_km: str
    Avg_HR_bpm: int
    Walk_Ratio_Percentage: float
    Aerobic_Decoupling_Percent: float
    Meters_Per_Heartbeat: float
    Avg_GCT_Balance_Left_Percent: float

class TopographyAnalysis(BaseModel):
    Total_Ascent_m: int
    Total_Descent_m: int
    Flat_Avg_Pace: str
    Uphill_Avg_Pace: str
    Downhill_Avg_Pace: str
    Uphill_VAM: int
    Avg_HR_Settlement_Latency_seconds: int

class MechanicalEfficiency(BaseModel):
    Avg_Vertical_Ratio_Percent: float
    Avg_Stride_Length_m: float
    Form_Decay_Delta: float

class DisciplineViolations(BaseModel):
    Seconds_Over_133: int
    Seconds_Over_138: int

class MetabolicZones(BaseModel):
    Zone_Recovery_Under_125_sec: int
    Zone_Base_125_to_133_sec: int
    Zone_Drift_134_to_138_sec: int
    Zone_Threshold_Over_138_sec: int

class TrackPoint(BaseModel):
    sec: int
    timestamp: str
    hr: Optional[int] = None
    cad: Optional[int] = None
    fractional_cadence: Optional[float] = None
    speed: Optional[float] = None
    vert_osc: Optional[float] = None

class LapData(BaseModel):
    Lap_Number: int
    Distance_m: float
    Duration_seconds: int
    Avg_Pace: str
    Avg_HR: int
    Min_HR: int
    Max_HR: int
    Avg_Cadence: int
    Avg_Vertical_Ratio: float
    Avg_GCT_ms: int
    Walk_Time_seconds: int
    Walk_Ratio_Percent: float
    Meters_Per_Heartbeat: float
    Ascent_m: int
    Descent_m: int
    Avg_Grade_Percent: float
    Avg_Vertical_Oscillation_mm: Optional[float] = None
    Track_Points_Stream: List[TrackPoint]

class FinalOutput(BaseModel):
    Metadata: Metadata
    Session_Macro: SessionMacro
    Topography_Analysis: TopographyAnalysis
    Mechanical_Efficiency: MechanicalEfficiency
    Discipline_Violations: DisciplineViolations
    Metabolic_Zones: MetabolicZones
    Lap_Data: List[LapData]

def send_ntfy_alert(output: FinalOutput, filename: str):
    try:
        topic = os.getenv("NTFY_TOPIC") or "running-analysis"
        topic_url = f"https://ntfy.sh/{topic}"
        
        # Build the structured, emoji-free message body
        body = (
            f"Course: {output.Metadata.Course_ID} ({output.Metadata.Total_Distance_m / 1000:.2f} km)\n"
            f"Pace: {output.Session_Macro.Avg_Pace_min_km}/km | HR: {output.Session_Macro.Avg_HR_bpm} bpm\n"
            f"Walk Ratio: {output.Session_Macro.Walk_Ratio_Percentage}% | VAM: {output.Topography_Analysis.Uphill_VAM}\n"
            f"Efficiency: {output.Session_Macro.Meters_Per_Heartbeat} m/hb | Form Decay: {output.Mechanical_Efficiency.Form_Decay_Delta}"
        )
        
        headers = {
            "Title": f"Run Processed: {filename}"
        }
        
        resp = requests.post(topic_url, data=body.encode('utf-8'), headers=headers, timeout=5)
        print(f"Ntfy alert sent to {topic_url}, status: {resp.status_code}")
    except Exception as e:
        print(f"Failed to send ntfy alert: {e}")

def format_pace(speed_m_s: float | None) -> str:
    if not speed_m_s or speed_m_s <= 0:
        return "00:00"
    pace_sec_km = 1000.0 / speed_m_s
    mins = int(pace_sec_km // 60)
    secs = int(pace_sec_km % 60)
    return f"{mins:02d}:{secs:02d}"

def process_file(file_path: str, force: bool = False):
    try:
        fitfile = FitFile(file_path)
        
        records = []
        laps_data = []
        session_data = None
        
        for message in fitfile.get_messages():
            if message.name == 'record':
                data = {}
                for field in message:
                    if field.value is not None:
                        data[field.name] = field.value
                records.append(data)
            elif message.name == 'lap':
                data = {}
                for field in message:
                    if field.value is not None:
                        data[field.name] = field.value
                laps_data.append(data)
            elif message.name == 'session':
                data = {}
                for field in message:
                    if field.value is not None:
                        data[field.name] = field.value
                session_data = data
                
        if not records:
            raise ValueError("No records found in FIT file.")
            
        start_time_workout = records[0].get('timestamp')
        date_str_json = start_time_workout.strftime('%Y-%m-%d') if start_time_workout else "Unknown"
        date_str_file = start_time_workout.strftime('%Y%m%d') if start_time_workout else "Unknown"

        # Calculate total distance
        if session_data and session_data.get('total_distance'):
            total_dist = session_data.get('total_distance')
        else:
            total_dist = records[-1].get('distance') or 0.0

        # Fast Check: Skip if output file already exists and force is False
        dist_prefix = str(int(round(total_dist / 100.0))) if total_dist else "0"
        new_filename = f"{dist_prefix}_{date_str_file}.json"
        output_dir = Path("Analyzed JSON Files")
        output_file = output_dir / new_filename
        
        if output_file.exists() and not force:
            print(f"Skipping {file_path} (output {new_filename} already exists).")
            return

        # Course ID
        dist_km = total_dist / 1000.0
        if 5.0 <= dist_km <= 5.3:
            course_id = "5.1km_Monday"
        elif 6.1 <= dist_km <= 6.5:
            course_id = "6.3km_Wednesday"
        elif 10.4 <= dist_km <= 10.7:
            course_id = "10.5km_Saturday"
        else:
            course_id = f"Other_{round(dist_km, 1)}km"

        # Prep lap timing logic
        import datetime
        laps_timing = []
        for lap in laps_data:
            start_t = lap.get('start_time')
            elapsed = lap.get('total_elapsed_time', 0.0)
            end_t = start_t + datetime.timedelta(seconds=elapsed) if start_t else None
            laps_timing.append({
                'start': start_t,
                'end': end_t,
                'walk_sec': 0,
                'move_sec': 0,
                'hrs': [],
                'gcts': [],
                'ascent': 0.0,
                'descent': 0.0,
                'prev_alt': None,
                'vert_oscs': [],
                'track_points': []
            })

        # Pass 1: Extract Base Metrics & Topography
        total_moving_sec = 0
        total_walking_sec = 0
        sum_hr = 0
        hr_count = 0
        
        sec_over_133 = 0
        sec_over_138 = 0
        
        z_rec = 0
        z_base = 0
        z_drift = 0
        z_thresh = 0
        
        moving_records = []
        
        # Form Decay
        first_2km_vrs = []
        last_2km_vrs = []
        all_vrs = []
        all_sls = []
        
        # Aerobic
        total_heartbeats = 0.0
        
        for r in records:
            speed = r.get('enhanced_speed') or r.get('speed')
            hr = r.get('heart_rate')
            dist = r.get('distance') or 0.0
            
            if hr is not None:
                sum_hr += hr
                hr_count += 1
                total_heartbeats += (hr / 60.0)
                if hr > 133:
                    sec_over_133 += 1
                if hr > 138:
                    sec_over_138 += 1
                    
                if hr < 125:
                    z_rec += 1
                elif 125 <= hr <= 133:
                    z_base += 1
                elif 134 <= hr <= 138:
                    z_drift += 1
                elif hr > 138:
                    z_thresh += 1

            if speed is not None and speed > 0:
                total_moving_sec += 1
                moving_records.append(r)
                
                # Single Calibration Gate: GCT > 300
                gct = r.get('stance_time')
                is_walking = False
                if gct is not None and gct > 300:
                    total_walking_sec += 1
                    is_walking = True
                    
                # Map to Lap
                ts = r.get('timestamp')
                if ts:
                    for lt in laps_timing:
                        if lt['start'] and lt['end'] and lt['start'] <= ts <= lt['end']:
                            lt['move_sec'] += 1
                            if is_walking:
                                lt['walk_sec'] += 1
                            if hr is not None:
                                lt['hrs'].append(hr)
                            if gct is not None:
                                lt['gcts'].append(gct)
                            
                            vo = r.get('vertical_oscillation')
                            if vo is not None:
                                lt['vert_oscs'].append(vo)
                            
                            # Track point stream
                            r_cad = r.get('cadence')
                            r_frac = r.get('fractional_cadence')
                            if r_cad is not None:
                                frac_val = r_frac if r_frac is not None else 0.0
                                cad_full = int(round((r_cad * 2) + frac_val))
                            else:
                                cad_full = None
                            
                            pt = TrackPoint(
                                sec=len(lt['track_points']) + 1,
                                timestamp=ts.strftime('%Y-%m-%d %H:%M:%S') if ts else "",
                                hr=hr,
                                cad=cad_full,
                                fractional_cadence=r_frac,
                                speed=round(speed, 2) if speed is not None else None,
                                vert_osc=round(vo, 1) if vo is not None else None
                            )
                            lt['track_points'].append(pt)
                            
                            alt = r.get('enhanced_altitude') or r.get('altitude')
                            if alt is not None:
                                if lt['prev_alt'] is not None:
                                    delta = alt - lt['prev_alt']
                                    if delta > 0:
                                        lt['ascent'] += delta
                                    elif delta < 0:
                                        lt['descent'] += abs(delta)
                                lt['prev_alt'] = alt
                            
                            break
                    
            vr = r.get('vertical_ratio')
            if vr is not None:
                all_vrs.append(vr)
                if dist <= 2000:
                    first_2km_vrs.append(vr)
                if (total_dist - dist) <= 2000:
                    last_2km_vrs.append(vr)
                    
            sl = r.get('step_length')
            if sl is not None:
                all_sls.append(sl / 1000.0)

        # GCT Balance parsing
        # Garmin often stores left percentage as `stance_time_balance / 100.0` or similar.
        gct_bals = [r.get('stance_time_balance') for r in records if r.get('stance_time_balance') is not None]
        avg_gct_bal = 0.0
        if gct_bals:
            # Garmin raw is often a value where percent = raw / 100, or a specific bitmask.
            # Usually for left balance, we can take value / 100.0
            avg_gct_bal = round(sum(gct_bals)/len(gct_bals) / 100.0, 1)

        walk_ratio = (total_walking_sec / total_moving_sec * 100.0) if total_moving_sec > 0 else 0.0
        meters_per_hb = total_dist / total_heartbeats if total_heartbeats > 0 else 0.0

        # Form Decay Logic
        form_decay_delta = 0.0
        if total_dist < 4000:
            if len(all_vrs) >= 2:
                half = len(all_vrs) // 2
                fh = sum(all_vrs[:half]) / half
                sh = sum(all_vrs[half:]) / (len(all_vrs) - half)
                form_decay_delta = sh - fh
        else:
            if first_2km_vrs and last_2km_vrs:
                fh = sum(first_2km_vrs) / len(first_2km_vrs)
                sh = sum(last_2km_vrs) / len(last_2km_vrs)
                form_decay_delta = sh - fh
                
        # Aerobic Decoupling
        decoupling_percent = 0.0
        if len(moving_records) >= 2:
            half_idx = len(moving_records) // 2
            first_half = moving_records[:half_idx]
            second_half = moving_records[half_idx:]
            
            fh_hrs = [r.get('heart_rate') for r in first_half if r.get('heart_rate')]
            fh_speeds = [r.get('enhanced_speed') or r.get('speed') for r in first_half if (r.get('enhanced_speed') or r.get('speed'))]
            sh_hrs = [r.get('heart_rate') for r in second_half if r.get('heart_rate')]
            sh_speeds = [r.get('enhanced_speed') or r.get('speed') for r in second_half if (r.get('enhanced_speed') or r.get('speed'))]
            
            if fh_hrs and fh_speeds and sh_hrs and sh_speeds:
                avg_hr_1 = sum(fh_hrs) / len(fh_hrs)
                avg_speed_1 = sum(fh_speeds) / len(fh_speeds)
                avg_hr_2 = sum(sh_hrs) / len(sh_hrs)
                avg_speed_2 = sum(sh_speeds) / len(sh_speeds)
                
                if avg_speed_1 > 0 and avg_speed_2 > 0:
                    ratio_1 = avg_hr_1 / avg_speed_1
                    ratio_2 = avg_hr_2 / avg_speed_2
                    if ratio_1 > 0:
                        decoupling_percent = ((ratio_2 - ratio_1) / ratio_1) * 100.0

        # Topography & Settlement
        grades = [0.0] * len(records)
        for i in range(len(records)):
            r = records[i]
            r_10 = records[max(0, i-10)]
            
            alt = r.get('enhanced_altitude') or r.get('altitude')
            alt_10 = r_10.get('enhanced_altitude') or r_10.get('altitude')
            
            dist = r.get('distance')
            dist_10 = r_10.get('distance')
            
            if alt is not None and alt_10 is not None and dist is not None and dist_10 is not None:
                delta_d = dist - dist_10
                delta_a = alt - alt_10
                if delta_d > 0:
                    grades[i] = (delta_a / delta_d) * 100.0
                    
        flat_speeds, flat_hrs = [], []
        up_speeds, up_hrs = [], []
        down_speeds, down_hrs = [], []
        
        total_up_ascent = 0.0
        total_up_seconds = 0
        
        for i in range(len(records)):
            r = records[i]
            g = grades[i]
            speed = r.get('enhanced_speed') or r.get('speed')
            hr = r.get('heart_rate')
            
            # For VAM: accumulate uphill ascent
            r_prev = records[max(0, i-1)]
            alt = r.get('enhanced_altitude') or r.get('altitude')
            alt_prev = r_prev.get('enhanced_altitude') or r_prev.get('altitude')
            
            if speed is not None and speed > 0:
                if g > 2.0:
                    up_speeds.append(speed)
                    if hr: up_hrs.append(hr)
                    total_up_seconds += 1
                    if alt is not None and alt_prev is not None and alt > alt_prev:
                        total_up_ascent += (alt - alt_prev)
                elif g < -2.0:
                    down_speeds.append(speed)
                    if hr: down_hrs.append(hr)
                else:
                    flat_speeds.append(speed)
                    if hr: flat_hrs.append(hr)
                    
        vam = 0
        if total_up_seconds > 0:
            vam = int(total_up_ascent / (total_up_seconds / 3600.0))

        # Settlement Latency State Machine
        latencies = []
        i = 0
        while i < len(records):
            if grades[i] > 2.0:
                hr = records[i].get('heart_rate')
                if hr and hr > 138:
                    # found uphill trigger > 138
                    # scan forward for end of uphill (grade < 1%)
                    j = i + 1
                    while j < len(records) and grades[j] >= 1.0:
                        j += 1
                        
                    if j < len(records):
                        # now count seconds until HR < 133
                        k = j
                        settled = False
                        while k < len(records):
                            k_hr = records[k].get('heart_rate')
                            if k_hr and k_hr < 133:
                                # Found settlement!
                                ts_start = records[j].get('timestamp')
                                ts_end = records[k].get('timestamp')
                                if ts_start and ts_end:
                                    latencies.append(int((ts_end - ts_start).total_seconds()))
                                settled = True
                                break
                            k += 1
                        if settled:
                            i = k # advance past this settlement
                        else:
                            break
                    else:
                        break
            i += 1

        avg_latency = int(sum(latencies)/len(latencies)) if latencies else 0

        # Lap Data Extraction
        lap_results = []
        for i_lap, lap in enumerate(laps_data):
            lap_num = i_lap + 1
            l_dist = lap.get('total_distance', 0.0)
            l_duration = int(round(lap.get('total_timer_time') or lap.get('total_elapsed_time') or 0))
            l_avg_speed = lap.get('enhanced_avg_speed') or lap.get('avg_speed')
            l_pace = format_pace(l_avg_speed)
            l_avg_hr = lap.get('avg_heart_rate', 0)
            l_avg_vr = lap.get('avg_vertical_ratio', 0.0)
            l_raw_cad = lap.get('avg_running_cadence')
            l_avg_cadence = (l_raw_cad * 2) if l_raw_cad is not None else 0
            
            lt = laps_timing[i_lap]
            w_sec = lt['walk_sec']
            m_sec = lt['move_sec']
            w_ratio = (w_sec / m_sec * 100.0) if m_sec > 0 else 0.0
            
            l_hrs = lt['hrs']
            l_min_hr = min(l_hrs) if l_hrs else 0
            l_max_hr = max(l_hrs) if l_hrs else 0
            l_hb = sum((h / 60.0) for h in l_hrs)
            l_mphb = l_dist / l_hb if l_hb > 0 else 0.0
            
            l_gcts = lt['gcts']
            l_avg_gct = int(sum(l_gcts)/len(l_gcts)) if l_gcts else 0
            
            l_asc = int(round(lt['ascent']))
            l_desc = int(round(lt['descent']))
            l_grade = ((lt['ascent'] - lt['descent']) / l_dist * 100.0) if l_dist > 0 else 0.0
            
            # Direct extraction from lap message first
            l_vo = lap.get('avg_vertical_oscillation')
            
            # Fallback to record-level average if not found in lap message
            if l_vo is None and lt['vert_oscs']:
                l_vo = sum(lt['vert_oscs']) / len(lt['vert_oscs'])
            
            l_avg_vo = round(l_vo, 1) if l_vo is not None else None
            
            lap_results.append(LapData(
                Lap_Number=lap_num,
                Distance_m=round(l_dist, 2),
                Duration_seconds=l_duration,
                Avg_Pace=l_pace,
                Avg_HR=int(l_avg_hr),
                Min_HR=l_min_hr,
                Max_HR=l_max_hr,
                Avg_Cadence=int(l_avg_cadence),
                Avg_Vertical_Ratio=round(l_avg_vr, 2),
                Avg_GCT_ms=l_avg_gct,
                Walk_Time_seconds=w_sec,
                Walk_Ratio_Percent=round(w_ratio, 2),
                Meters_Per_Heartbeat=round(l_mphb, 2),
                Ascent_m=l_asc,
                Descent_m=l_desc,
                Avg_Grade_Percent=round(l_grade, 2),
                Avg_Vertical_Oscillation_mm=l_avg_vo,
                Track_Points_Stream=lt['track_points']
            ))

        # Construct Final JSON
        avg_speed_all = sum((r.get('enhanced_speed') or r.get('speed', 0.0)) for r in moving_records if (r.get('enhanced_speed') or r.get('speed'))) / len(moving_records) if moving_records else 0.0
        
        metadata = Metadata(
            Date=date_str_json,
            Course_ID=course_id,
            Total_Distance_m=round(total_dist, 2)
        )
        
        engine = SessionMacro(
            Avg_Pace_min_km=format_pace(avg_speed_all),
            Avg_HR_bpm=int(sum_hr/hr_count) if hr_count else 0,
            Walk_Ratio_Percentage=round(walk_ratio, 2),
            Aerobic_Decoupling_Percent=round(decoupling_percent, 2),
            Meters_Per_Heartbeat=round(meters_per_hb, 2),
            Avg_GCT_Balance_Left_Percent=avg_gct_bal
        )
        
        flat_avg_spd = sum(flat_speeds)/len(flat_speeds) if flat_speeds else 0.0
        up_avg_spd = sum(up_speeds)/len(up_speeds) if up_speeds else 0.0
        down_avg_spd = sum(down_speeds)/len(down_speeds) if down_speeds else 0.0
        
        tot_asc = int(session_data.get('total_ascent', 0)) if session_data else 0
        tot_desc = int(session_data.get('total_descent', 0)) if session_data else 0
        
        topography = TopographyAnalysis(
            Total_Ascent_m=tot_asc,
            Total_Descent_m=tot_desc,
            Flat_Avg_Pace=format_pace(flat_avg_spd),
            Uphill_Avg_Pace=format_pace(up_avg_spd),
            Downhill_Avg_Pace=format_pace(down_avg_spd),
            Uphill_VAM=vam,
            Avg_HR_Settlement_Latency_seconds=avg_latency
        )
        
        mech = MechanicalEfficiency(
            Avg_Vertical_Ratio_Percent=round(sum(all_vrs)/len(all_vrs), 2) if all_vrs else 0.0,
            Avg_Stride_Length_m=round(sum(all_sls)/len(all_sls), 3) if all_sls else 0.0,
            Form_Decay_Delta=round(form_decay_delta, 2)
        )
        
        disc = DisciplineViolations(
            Seconds_Over_133=sec_over_133,
            Seconds_Over_138=sec_over_138
        )
        
        zones = MetabolicZones(
            Zone_Recovery_Under_125_sec=z_rec,
            Zone_Base_125_to_133_sec=z_base,
            Zone_Drift_134_to_138_sec=z_drift,
            Zone_Threshold_Over_138_sec=z_thresh
        )
        
        final_output = FinalOutput(
            Metadata=metadata,
            Session_Macro=engine,
            Topography_Analysis=topography,
            Mechanical_Efficiency=mech,
            Discipline_Violations=disc,
            Metabolic_Zones=zones,
            Lap_Data=lap_results
        )
        
        print(final_output.model_dump_json(indent=2))
        
        output_dir = Path("Analyzed JSON Files")
        output_dir.mkdir(exist_ok=True)
        
        dist_prefix = str(int(round(total_dist / 100.0))) if total_dist else "0"
        new_filename = f"{dist_prefix}_{date_str_file}.json"
        
        output_file = output_dir / new_filename
        output_file.write_text(final_output.model_dump_json(indent=2))
        
        # Send push notification
        send_ntfy_alert(final_output, new_filename)
        
    except Exception as e:
        print(f"Error processing FIT file: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Analyze Garmin FIT file.")
    parser.add_argument("file_path", help="Path to the FIT file.")
    parser.add_argument("--force", action="store_true", help="Force recalculation even if JSON exists.")
    args = parser.parse_args()
    
    process_file(args.file_path, force=args.force)
