"""업계별 SaaS 제품명용 영어 단어뱅크 (2026-08-11 프로젝트 정의 전환).

CLAUDE.md 1장: 수요/공급 검증 없이, 전세계 다양한 업계의 전문용어에서
추출한 단어를 조합해 2단어 Title Case 제목을 생성한다. 이 파일의 단어는
`ACTIVE_ISSUES.md`의 `INDUSTRY_TERMS` 큐레이션과 같은 방식(AI 지식 기반
큐레이션, 웹 스크래핑 없음)으로 선정했다.

DOMAIN_WORDS: 업계별로 그 업계를 연상시키는 명사(업무 대상·문서·프로세스).
FUNCTION_WORDS: 업계에 무관하게 "이 도구가 무엇을 하는지"를 연상시키는
동작/역할 명사. 제목은 "도메인어 + 기능어" 순서로 조합한다(design 9.2의
"대상+기능, 업무+도구" 조합 구조를 기회 대신 단어뱅크에 적용) — 완전 무작위
두 단어 조합보다 "어떤 SaaS인지 추측 가능"한 이름이 나올 확률이 높다.

업계 커버리지는 의도적으로 넓게 잡았다(북미 SMB 업계 관행에 익숙한 영어
전문용어 위주 — "전세계"를 완전히 대표한다고 주장하지 않음, 후속 세션이
특정 지역/언어권을 넓히고 싶으면 이 구조에 새 업계 키만 추가하면 된다).
"""

from __future__ import annotations

DOMAIN_WORDS: dict[str, tuple[str, ...]] = {
    "healthcare": (
        "Patient", "Referral", "Prior", "Claim", "Provider", "Appointment",
        "Prescription", "Insurance", "Diagnosis", "Discharge", "Intake", "Consent",
    ),
    "finance": (
        "Ledger", "Invoice", "Payroll", "Expense", "Budget", "Payment",
        "Reconciliation", "Audit", "Accrual", "Refund", "Chargeback", "Escrow",
    ),
    "legal": (
        "Contract", "Docket", "Filing", "Clause", "Compliance", "Redline",
        "Matter", "Deposition", "Waiver", "Retainer", "Discovery", "Statute",
    ),
    "logistics": (
        "Freight", "Shipment", "Manifest", "Customs", "Warehouse", "Pallet",
        "Container", "Route", "Fleet", "Dispatch", "Inventory", "Backorder",
    ),
    "real_estate": (
        "Lease", "Tenant", "Property", "Listing", "Escrow", "Inspection",
        "Maintenance", "Deposit", "Rent", "Title", "Zoning", "Appraisal",
    ),
    "insurance": (
        "Policy", "Premium", "Underwriting", "Claim", "Adjuster", "Coverage",
        "Deductible", "Subrogation", "Renewal", "Actuary", "Rider", "Binder",
    ),
    "hr_payroll": (
        "Onboarding", "Timesheet", "Benefits", "Roster", "Shift", "Leave",
        "Recruiting", "Payroll", "Offboarding", "Compliance", "Candidate", "Review",
    ),
    "construction": (
        "Permit", "Blueprint", "Punchlist", "Subcontractor", "Bid", "Change",
        "Inspection", "Material", "Crew", "Jobsite", "Warranty", "Lien",
    ),
    "retail_ecommerce": (
        "Inventory", "Variant", "Checkout", "Return", "Fulfillment", "Vendor",
        "Catalog", "Storefront", "Loyalty", "Markdown", "Restock", "Bundle",
    ),
    "hospitality": (
        "Reservation", "Guest", "Housekeeping", "Checkin", "Amenity", "Concierge",
        "Occupancy", "Booking", "Banquet", "Itinerary", "Shuttle", "Feedback",
    ),
    "education": (
        "Enrollment", "Curriculum", "Attendance", "Transcript", "Tuition", "Grading",
        "Cohort", "Syllabus", "Advisor", "Scholarship", "Classroom", "Alumni",
    ),
    "manufacturing": (
        "Production", "Assembly", "Quality", "Defect", "Downtime", "Maintenance",
        "Scheduling", "Batch", "Yield", "Supplier", "Calibration", "Throughput",
    ),
    "agriculture": (
        "Harvest", "Livestock", "Irrigation", "Yield", "Crop", "Soil",
        "Pesticide", "Grazing", "Greenhouse", "Fertilizer", "Rotation", "Silo",
    ),
    "energy_utilities": (
        "Meter", "Outage", "Grid", "Consumption", "Billing", "Maintenance",
        "Substation", "Demand", "Efficiency", "Compliance", "Inspection", "Permit",
    ),
    "nonprofit": (
        "Donor", "Grant", "Volunteer", "Campaign", "Fundraising", "Pledge",
        "Beneficiary", "Impact", "Membership", "Outreach", "Stewardship", "Ledger",
    ),
    "government": (
        "Permit", "Citation", "Ordinance", "Zoning", "Constituent", "Hearing",
        "Records", "Licensing", "Compliance", "Inspection", "Franchise", "Ballot",
    ),
    "marketing": (
        "Campaign", "Audience", "Funnel", "Attribution", "Brand", "Creative",
        "Engagement", "Referral", "Conversion", "Segment", "Content", "Placement",
    ),
    "media_publishing": (
        "Editorial", "Subscriber", "Royalty", "Syndication", "Manuscript", "Archive",
        "Broadcast", "Licensing", "Distribution", "Rights", "Circulation", "Feed",
    ),
    "transportation": (
        "Route", "Fleet", "Fuel", "Maintenance", "Dispatch", "Driver",
        "Compliance", "Mileage", "Terminal", "Cargo", "Schedule", "Permit",
    ),
    "telecom": (
        "Subscriber", "Provisioning", "Outage", "Bandwidth", "Billing", "Roaming",
        "Ticket", "Coverage", "Latency", "Churn", "Activation", "Network",
    ),
    "cybersecurity": (
        "Incident", "Vulnerability", "Access", "Credential", "Threat", "Audit",
        "Compliance", "Endpoint", "Breach", "Firewall", "Patch", "Perimeter",
    ),
    "it_devops": (
        "Deployment", "Incident", "Uptime", "Backup", "Provisioning", "Pipeline",
        "Rollback", "Monitoring", "Capacity", "Migration", "Configuration", "Runbook",
    ),
    "customer_support": (
        "Ticket", "Escalation", "Response", "Satisfaction", "Queue", "Refund",
        "Warranty", "Feedback", "Resolution", "Knowledge", "Chat", "Callback",
    ),
    "recruiting": (
        "Candidate", "Pipeline", "Interview", "Offer", "Sourcing", "Reference",
        "Screening", "Requisition", "Onboarding", "Assessment", "Placement", "Referral",
    ),
    "events": (
        "Registration", "Attendee", "Venue", "Sponsor", "Badge", "Agenda",
        "Ticketing", "Exhibitor", "Session", "Catering", "Logistics", "Feedback",
    ),
    "automotive": (
        "Warranty", "Service", "Inspection", "Inventory", "Trade", "Financing",
        "Recall", "Maintenance", "Dealer", "Fleet", "Mileage", "Appraisal",
    ),
    "food_service": (
        "Inventory", "Recipe", "Supplier", "Reservation", "Delivery", "Compliance",
        "Waste", "Menu", "Catering", "Staffing", "Allergen", "Franchise",
    ),
}

FUNCTION_WORDS: tuple[str, ...] = (
    "Guard", "Tracker", "Sync", "Flow", "Hub", "Pilot", "Desk", "Radar",
    "Relay", "Vault", "Compass", "Beacon", "Forge", "Cascade", "Bridge",
    "Anchor", "Signal", "Watch", "Scope", "Loop", "Grid", "Pulse", "Wave",
    "Path", "Point", "Lock", "Map", "Lens", "Frame", "Base", "Core",
    "Ledger", "Board", "Deck", "Studio", "Lab", "Station", "Terminal",
    "Center", "Zone", "Portal", "Console", "Panel", "Dial", "Meter",
    "Scale", "Route", "Dock", "Rail", "Trail", "Chain", "Ring", "Node",
    "Gate", "Nexus", "Atlas", "Sentry", "Keeper", "Manager",
)


def all_industries() -> tuple[str, ...]:
    return tuple(DOMAIN_WORDS.keys())


def all_domain_words() -> list[tuple[str, str]]:
    """(industry, word) pairs, in a stable, deterministic order."""
    return [(industry, word) for industry, words in DOMAIN_WORDS.items() for word in words]
