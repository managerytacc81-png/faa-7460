#!/usr/bin/env python3
"""
FAA 14 CFR Part 77 Airspace Obstruction Evaluation & OE/AAA Lapse Tracking Engine
Automates Form 7460-1 Notice of Proposed Construction determination requirements:
- 14 CFR 77.9(a): >200 ft AGL threshold
- 14 CFR 77.9(b)(1): 100:1 slope within 20,000 ft of runway (>3,200 ft)
- 14 CFR 77.9(b)(2): 50:1 slope within 10,000 ft of runway (<=3,200 ft)
- 14 CFR 77.9(b)(3): 25:1 slope within 5,000 ft of heliport
- OE/AAA Docket Ingestion & 18-Month Determination Lapse Monitor
"""

import argparse
import datetime
import json
import math
import os
import sys
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple

EARTH_RADIUS_FEET = 20902231.0  # WGS-84 mean radius in feet

def haversine_distance_feet(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two coordinates in feet using Haversine formula."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_FEET * c

@dataclass
class AirportRunway:
    code: str
    name: str
    lat: float
    lon: float
    elevation_amsl: float
    runway_length_feet: float
    is_heliport: bool = False

@dataclass
class ScreenResult:
    notice_required: bool
    reasons: List[str]
    max_allowable_height_agl: float
    exceeded_surfaces: List[Dict[str, Any]]
    total_elevation_amsl: float

class Part77EvaluationEngine:
    """Evaluates proposed structures (cranes, towers, turbines, buildings) against 14 CFR Part 77."""

    @staticmethod
    def evaluate(
        site_lat: float,
        site_lon: float,
        site_elevation_amsl: float,
        structure_height_agl: float,
        nearby_runways: List[AirportRunway]
    ) -> ScreenResult:
        reasons = []
        exceeded_surfaces = []
        total_amsl = site_elevation_amsl + structure_height_agl
        lowest_limiting_agl = 200.0  # baseline maximum height before notice

        # Criteria 1: 14 CFR 77.9(a) - Any structure > 200 ft AGL anywhere
        if structure_height_agl > 200.0:
            reasons.append(f"Structure height ({structure_height_agl:.1f} ft AGL) exceeds the 200.0 ft AGL blanket threshold [§ 77.9(a)].")

        # Criteria 2: 14 CFR 77.9(b) - Runway slope surfaces
        for rw in nearby_runways:
            dist_feet = haversine_distance_feet(site_lat, site_lon, rw.lat, rw.lon)

            if rw.is_heliport:
                # 25:1 slope within 5,000 ft
                if dist_feet <= 5000.0:
                    max_allowed_amsl = rw.elevation_amsl + (dist_feet / 25.0)
                    allowed_agl_here = max(0.0, max_allowed_amsl - site_elevation_amsl)
                    lowest_limiting_agl = min(lowest_limiting_agl, allowed_agl_here)
                    if total_amsl > max_allowed_amsl:
                        penetration = total_amsl - max_allowed_amsl
                        reasons.append(
                            f"Penetrates 25:1 heliport surface for {rw.code} by {penetration:.1f} ft "
                            f"(Distance: {dist_feet:,.0f} ft, Max Allowed AGL: {allowed_agl_here:.1f} ft) [§ 77.9(b)(3)]."
                        )
                        exceeded_surfaces.append({
                            "facility": rw.code,
                            "type": "Heliport 25:1",
                            "distance_feet": dist_feet,
                            "allowed_agl": allowed_agl_here,
                            "penetration_feet": penetration
                        })
            elif rw.runway_length_feet > 3200.0:
                # 100:1 slope within 20,000 ft
                if dist_feet <= 20000.0:
                    max_allowed_amsl = rw.elevation_amsl + (dist_feet / 100.0)
                    allowed_agl_here = max(0.0, max_allowed_amsl - site_elevation_amsl)
                    lowest_limiting_agl = min(lowest_limiting_agl, allowed_agl_here)
                    if total_amsl > max_allowed_amsl:
                        penetration = total_amsl - max_allowed_amsl
                        reasons.append(
                            f"Penetrates 100:1 runway slope for {rw.code} (Runway > 3,200ft) by {penetration:.1f} ft "
                            f"(Distance: {dist_feet:,.0f} ft, Max Allowed AGL: {allowed_agl_here:.1f} ft) [§ 77.9(b)(1)]."
                        )
                        exceeded_surfaces.append({
                            "facility": rw.code,
                            "type": "Airport 100:1",
                            "distance_feet": dist_feet,
                            "allowed_agl": allowed_agl_here,
                            "penetration_feet": penetration
                        })
            else:
                # 50:1 slope within 10,000 ft
                if dist_feet <= 10000.0:
                    max_allowed_amsl = rw.elevation_amsl + (dist_feet / 50.0)
                    allowed_agl_here = max(0.0, max_allowed_amsl - site_elevation_amsl)
                    lowest_limiting_agl = min(lowest_limiting_agl, allowed_agl_here)
                    if total_amsl > max_allowed_amsl:
                        penetration = total_amsl - max_allowed_amsl
                        reasons.append(
                            f"Penetrates 50:1 runway slope for {rw.code} (Runway <= 3,200ft) by {penetration:.1f} ft "
                            f"(Distance: {dist_feet:,.0f} ft, Max Allowed AGL: {allowed_agl_here:.1f} ft) [§ 77.9(b)(2)]."
                        )
                        exceeded_surfaces.append({
                            "facility": rw.code,
                            "type": "Airport 50:1",
                            "distance_feet": dist_feet,
                            "allowed_agl": allowed_agl_here,
                            "penetration_feet": penetration
                        })

        return ScreenResult(
            notice_required=len(reasons) > 0,
            reasons=reasons,
            max_allowable_height_agl=lowest_limiting_agl,
            exceeded_surfaces=exceeded_surfaces,
            total_elevation_amsl=total_amsl
        )

# ---------------------------------------------------------
# OE/AAA Determination & Expiration Tracker
# ---------------------------------------------------------

class OEAAALapseTracker:
    """Tracks FAA OE/AAA determinations, renewal deadlines, and 7460-2 notices."""

    @staticmethod
    def evaluate_case(case_number: str, determination_date: str, structure_status: str = "PROPOSED") -> Dict[str, Any]:
        """
        Determinations of No Hazard lapse after 18 months unless:
        - Construction has commenced (Form 7460-2 Part 1 filed)
        - An extension request is submitted at least 15 days before expiration.
        """
        dt = datetime.datetime.strptime(determination_date, "%Y-%m-%d").date()
        # 18 months = approx 548 days
        expiration_date = dt + datetime.timedelta(days=548)
        today = datetime.date.today()
        days_remaining = (expiration_date - today).days

        if structure_status == "COMPLETED":
            status = "CONSTRUCTED_PERMANENT"
            action = "Ensure Form 7460-2 Part 2 (Final Notice) is recorded."
        elif days_remaining < 0:
            status = "LAPSED_EXPIRED"
            action = "Determination lapsed. New Form 7460-1 filing required before erection."
        elif days_remaining <= 45:
            status = "CRITICAL_LAPSE_RISK"
            action = f"File FAA Extension Request or Form 7460-2 Part 1 immediately ({days_remaining} days left)."
        elif days_remaining <= 90:
            status = "RENEWAL_WINDOW_OPEN"
            action = f"Prepare extension request or verify crane mobilization schedule ({days_remaining} days left)."
        else:
            status = "ACTIVE_VALID"
            action = f"Determination active. Expiration: {expiration_date.isoformat()} ({days_remaining} days left)."

        return {
            "case_number": case_number,
            "determination_date": determination_date,
            "expiration_date": expiration_date.isoformat(),
            "days_remaining": days_remaining,
            "status": status,
            "required_action": action
        }

# ---------------------------------------------------------
# CLI & Demonstration
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FAA Part 77 Airspace Notice & OE/AAA Lapse Tracker")
    subparsers = parser.add_subparsers(dest="command")

    # Screen command
    screen_p = subparsers.add_parser("screen", help="Evaluate proposed structure against Part 77 criteria")
    screen_p.add_argument("--lat", type=float, required=True, help="Site latitude (decimal degrees)")
    screen_p.add_argument("--lon", type=float, required=True, help="Site longitude (decimal degrees)")
    screen_p.add_argument("--elevation", type=float, default=0.0, help="Site ground elevation AMSL in feet")
    screen_p.add_argument("--height", type=float, required=True, help="Structure height AGL in feet")

    # Track command
    track_p = subparsers.add_parser("track", help="Track OE/AAA determination lapse status")
    track_p.add_argument("--case", required=True, help="FAA Case Number (e.g., 2025-AWP-10442-OE)")
    track_p.add_argument("--date", required=True, help="Determination Date (YYYY-MM-DD)")

    args = parser.parse_args()

    if args.command == "screen":
        # Sample reference airport (e.g. McCarran / Harry Reid Intl LAS, runway 8L/26R)
        sample_airports = [
            AirportRunway(code="KLAS-26R", name="Harry Reid International", lat=36.0800, lon=-115.1522, elevation_amsl=2181.0, runway_length_feet=14515.0),
            AirportRunway(code="KHND-35R", name="Henderson Executive", lat=35.9728, lon=-115.1344, elevation_amsl=2492.0, runway_length_feet=6501.0),
            AirportRunway(code="NV-HELI", name="University Medical Center Heliport", lat=36.1580, lon=-115.1660, elevation_amsl=2030.0, runway_length_feet=60.0, is_heliport=True)
        ]
        result = Part77EvaluationEngine.evaluate(args.lat, args.lon, args.elevation, args.height, sample_airports)
        print("\n🛩️  FAA Part 77 Airspace Obstruction Screening Report")
        print("=" * 65)
        print(f"Notice Required (Form 7460-1): {'🚨 YES - MANDATORY FILING' if result.notice_required else '✅ NO - EXEMPT'}")
        print(f"Maximum Allowed Height (AGL):  {result.max_allowable_height_agl:.1f} ft")
        print(f"Total Elevation (AMSL):        {result.total_elevation_amsl:.1f} ft")
        print("=" * 65)
        if result.reasons:
            print("Specific Criteria Triggered:")
            for r in result.reasons:
                print(f"  • {r}")
        else:
            print("Structure does not penetrate 200 ft AGL or any nearby 100:1 / 50:1 / 25:1 airspace surfaces.")
        print()

    elif args.command == "track":
        res = OEAAALapseTracker.evaluate_case(args.case, args.date)
        print("\n📋 FAA OE/AAA Determination Docket Status")
        print("=" * 65)
        print(f"Case Number:         {res['case_number']}")
        print(f"Determination Date:  {res['determination_date']}")
        print(f"Lapse / Expiration:  {res['expiration_date']} ({res['days_remaining']} days remaining)")
        print(f"Docket Status:       {res['status']}")
        print(f"Action Required:     {res['required_action']}")
        print("=" * 65 + "\n")

    else:
        # Default self-test demo
        print("Running FAA Part 77 Self-Test...")
        sample_airports = [
            AirportRunway(code="KLAS-26R", name="Harry Reid International", lat=36.0800, lon=-115.1522, elevation_amsl=2181.0, runway_length_feet=14515.0)
        ]
        # Tower crane 180 ft tall, 2.5 miles (13,200 ft) from runway
        res = Part77EvaluationEngine.evaluate(36.1050, -115.1700, 2100.0, 180.0, sample_airports)
        print(f"Notice Required: {res.notice_required} | Reasons: {res.reasons}")
        track = OEAAALapseTracker.evaluate_case("2025-AWP-12345-OE", "2025-06-01")
        print(f"Docket Status: {track['status']} | {track['required_action']}")

if __name__ == "__main__":
    main()
