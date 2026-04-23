# Cybersecurity And Cyber-Physical Resilience

## Research Intent

This track studies cybersecurity as a resilience problem for critical infrastructure. The goal is to understand how cyber incidents can interrupt public services, delay restoration, strain cross-sector dependencies, or amplify physical hazards.

The working posture is defensive and aggregate. Findings should help compare sectors, identify dependency classes, and model public consequences without compiling attack instructions, target lists, credentials, or sensitive system architecture.

## Safe Scope

Use this track for:

- sector-level cyber risk summaries
- IT, OT, cloud, vendor, identity, and recovery dependencies
- public incident trends and regulatory context
- defensive frameworks and preparedness baselines
- cyber-physical interdependence modeling
- coarse geography such as national, regional, state, or sector summaries

Do not use this track for:

- exploit steps, payloads, or weaponized procedures
- exposed-service lists, IP addresses, credentials, or secrets
- facility-specific remote access paths or network diagrams
- precise operational technology architecture for named sensitive sites
- instructions that would enable unauthorized access or disruption

## Initial Framing

Cybersecurity belongs in this project because every major sector now depends on shared digital services:

- identity and access systems
- cloud and SaaS platforms
- telecom backhaul and routing
- vendor-managed software and remote support
- operational technology and industrial control systems
- endpoint fleets, logging, and backup infrastructure
- incident reporting and mutual-aid channels

The first analysis layer should track where a cyber event can become a public-impact event. In this repository, that means linking cyber risk themes to service interruption, patient safety, water quality, electric reliability, fuel distribution, logistics delay, payment disruption, emergency response degradation, or loss of public communications.

## Cross-Sector Dependency Map

| Dependency | Why It Matters | Safe Research Unit |
| --- | --- | --- |
| Identity and access | Credential compromise can spread across IT, cloud, vendors, and remote administration. | Sector-level MFA, privileged-access, and deprovisioning posture summaries. |
| Cloud and SaaS | Outages or account compromise can affect dispatch, records, billing, telemetry, public alerts, and coordination. | Provider class, service category, and recovery dependency summaries. |
| Telecom | Cyber response, remote operations, payment systems, hospitals, and emergency services all depend on communications availability. | Regional telecom dependency, not exact routes or network maps. |
| Operational technology | OT incidents can create safety, reliability, water, manufacturing, building-control, or transportation effects. | Framework-based OT risk classes and aggregate sector exposure. |
| Vendors and managed service providers | Shared vendors can become concentration points across many operators. | Vendor role categories and supply-chain risk themes. |
| Backup and recovery | Ransomware impact is often determined by restoration speed and backup isolation. | Recovery-time assumptions by sector or organization class. |
| Incident reporting | Timely reporting improves shared warning and assistance. | Regulatory and voluntary reporting pathways by sector. |

## Defensive Measures To Track

The first scorecard should be framework-based instead of target-based. Useful indicators include:

- asset inventory coverage for IT and OT
- known-exploited-vulnerability remediation process
- phishing-resistant MFA for privileged and remote access
- separation of user and privileged accounts
- network segmentation between IT and OT where applicable
- logging coverage and retention for critical systems
- offline or immutable backup coverage
- incident-response plan testing
- vendor security requirements and third-party incident reporting
- OT-specific cybersecurity training for staff responsible for OT systems
- recovery planning for degraded manual operations

## Sector Starting Points

### Energy

Track bulk electric system cyber regulation, distribution-system cybersecurity baselines, distributed energy resource risk, control-center resilience, vendor access, and restoration planning. Keep generation and transmission cyber findings at sector or regional level unless a source is already aggregated.

### Water And Wastewater

Track cyber hygiene for small and midsize utilities, HMI exposure guidance, backup operations, chemical dosing integrity, power dependence, and mutual aid. Avoid compiling named-utility control details.

### Healthcare

Track ransomware resilience, electronic health record dependence, medical device and imaging system risk, third-party billing or claims dependencies, downtime procedures, and patient-safety consequences.

### Communications And IT

Track secure-by-design expectations, cloud service concentration, software supply-chain dependency, telecom dependency for incident response, and the role of IT providers as shared infrastructure.

### Finance And Payments

Track payment continuity, account takeover and fraud trends, bank and processor dependency, cash logistics, cloud concentration, and incident reporting overlap. Keep analysis focused on systemic continuity and public economic effects.

### Transportation And Logistics

Track cyber dependence in port operations, rail dispatch, aviation systems, fleet management, fuel logistics, warehouse systems, and customs or trade documentation. Use generalized corridors and sector summaries.

## Data Model

Use `schemas/cyber-risk-summary.schema.json` for curated cyber findings. Each record should describe a public, defensive, aggregate risk theme and explicitly confirm that sensitive operational details were excluded.

Recommended fields to normalize first:

- `sector`
- `dependency_type`
- `risk_theme`
- `public_consequence`
- `defensive_focus`
- `data_granularity`
- `source_name`
- `source_url`
- `verified_date`
- `confidence`

## Immediate Work Queue

1. Build a cybersecurity source log from official CISA, NIST, DOE, EPA, HHS, FBI, FERC, and NERC references.
2. Create a small seed table of cross-sector cyber dependencies using only national or sector-level public information.
3. Add cyber dependency tags to the existing sector briefs as those files are created.
4. Decide whether the simulator should represent cyber events as direct sector stressors, dependency multipliers, or recovery-delay modifiers.
5. Revisit current CIRCIA reporting status before making any compliance statements, because the final-rule timeline and effective date may change.
