# Cybersecurity Source Log

This source log supports defensive, aggregate cybersecurity and cyber-physical resilience research. It should not be used to build exploit guides, target lists, exposed-system inventories, credential collections, or facility-specific cyber architecture maps.

## Official And Standards Sources

### CISA Critical Infrastructure Sectors

- URL: https://www.cisa.gov/topics/critical-infrastructure-security-and-resilience/critical-infrastructure-sectors
- Verified: April 23, 2026
- Use: baseline sector taxonomy for the 16 U.S. critical infrastructure sectors
- Notes: useful for aligning cyber findings with the rest of this repository's sector structure

### CISA Cross-Sector Cybersecurity Performance Goals

- URL: https://www.cisa.gov/cybersecurity-performance-goals
- Verified: April 23, 2026
- Use: defensive baseline for high-impact cybersecurity practices across critical infrastructure
- Notes: CISA presents the goals as voluntary practices for IT and OT owners; use for scorecards and maturity summaries, not as a full control framework

### CISA Cybersecurity Performance Goals Detail Page

- URL: https://www.cisa.gov/cybersecurity-performance-goals-cpgs
- Verified: April 23, 2026
- Use: individual CPG outcomes, recommended actions, IT/OT scope, and mapping to common threat themes
- Notes: useful for normalizing defensive indicators such as asset inventory, KEV remediation, MFA, segmentation, logging, incident reporting, and recovery planning

### NIST Cybersecurity Framework 2.0

- URL: https://www.nist.gov/publications/nist-cybersecurity-framework-csf-20
- Verified: April 23, 2026
- Use: high-level governance and risk-management vocabulary
- Notes: CSF 2.0 was published February 26, 2024 and organizes outcomes around Govern, Identify, Protect, Detect, Respond, and Recover

### NIST SP 800-82 Rev. 3, Guide to Operational Technology Security

- URL: https://csrc.nist.gov/pubs/sp/800/82/r3/final
- Verified: April 23, 2026
- Use: OT/ICS security concepts, safety and availability constraints, and cyber-physical risk framing
- Notes: use for defensive summaries only; avoid reproducing system topology details for named facilities

### DOE Cybersecurity Capability Maturity Model

- URL: https://www.energy.gov/ceser/cybersecurity-capability-maturity-model-c2m2
- Verified: April 23, 2026
- Use: maturity model for IT and OT cybersecurity capability, especially energy-sector resilience
- Notes: DOE lists Version 2.1 as the latest version, released June 2022

### DOE And NARUC Cybersecurity Baselines For Electric Distribution Systems And DER

- URL: https://www.naruc.org/core-sectors/critical-infrastructure-and-cybersecurity/cybersecurity-for-utility-regulators/cybersecurity-baselines/
- Verified: April 23, 2026
- Use: electric distribution and distributed energy resource cybersecurity baselines
- Notes: useful for the parts of the electric system not directly covered by bulk-electric NERC CIP framing

### FERC Cyber And Grid Security

- URL: https://www.ferc.gov/cyber-and-grid-security
- Verified: April 23, 2026
- Use: federal regulatory context for bulk power system reliability and mandatory cybersecurity reliability standards
- Notes: FERC identifies NERC as the Electric Reliability Organization that develops Critical Infrastructure Protection standards

### NERC Reliability Standards

- URL: https://nerc.com/pa/Stand/Pages/ReliabilityStandards.aspx
- Verified: April 23, 2026
- Use: current reliability standards index, including the Critical Infrastructure Protection standard family
- Notes: use for standards status and citations, not for extracting sensitive implementation assumptions about specific responsible entities

### CISA Known Exploited Vulnerabilities Catalog

- URL: https://www.cisa.gov/known-exploited-vulnerabilities-catalog
- Verified: April 23, 2026
- Use: defensive vulnerability-prioritization reference
- Notes: use for aggregate remediation themes; do not turn this into an exploit checklist

### CISA ICS Advisories

- URL: https://www.cisa.gov/news-events/ics-advisories
- Verified: April 23, 2026
- Use: aggregate tracking of OT, ICS, IoT, and medical-device advisory volume and mitigation themes
- Notes: use vendor and product details only when needed for defensive trend analysis; avoid facility mapping or exploitation detail

### EPA Cybersecurity For The Water Sector

- URL: https://www.epa.gov/waterresilience/epa-cybersecurity-water-sector
- Verified: April 23, 2026
- Use: water and wastewater cybersecurity guidance
- Notes: useful for small and midsize utility risk themes, HMI exposure guidance, and cyber hygiene practices

### HHS HPH Cybersecurity Performance Goals

- URL: https://hhscyber.hhs.gov/performance-goals.html
- Verified: April 23, 2026
- Use: healthcare and public health sector cybersecurity performance goals
- Notes: useful for patient-safety-centered cyber resilience, ransomware preparation, vendor risk, and healthcare downtime planning

### FBI IC3 Annual Reports

- URL: https://www.ic3.gov/AnnualReport/Reports/Reports/
- Verified: April 23, 2026
- Use: public cybercrime, fraud, ransomware, state, and annual reporting trends
- Notes: IC3 lists 2025 annual and state reports; use for high-level trend context, not facility-specific infrastructure conclusions

### CISA CIRCIA Rulemaking

- URL: https://www.cisa.gov/topics/cyber-threats-and-advisories/information-sharing/cyber-incident-reporting-critical-infrastructure-act-2022-circia
- Verified: April 23, 2026
- Use: cyber incident reporting policy context for critical infrastructure
- Notes: re-verify before making compliance claims; CISA's page says reporting requirements become effective only after the Final Rule goes into effect

### CISA Secure By Design Pledge

- URL: https://www.cisa.gov/securebydesign/pledge
- Verified: April 23, 2026
- Use: software-manufacturer responsibility, secure defaults, logging, MFA, vulnerability disclosure, patching, and vulnerability-class reduction themes
- Notes: especially relevant to IT-sector dependency and software supply-chain risk

## Handling Notes

- Prefer official government, regulator, standards, and sector-risk-management sources.
- Use current cyber threat sources only for defensive context, trend summaries, and mitigation themes.
- Do not store exploit procedure details, exposed-system identifiers, credentials, private vulnerability reports, or named-facility cyber architecture.
- If a source contains both defensive guidance and weaponizable detail, summarize only the defensive guidance and link to the source rather than copying sensitive detail.
- Mark all curated records with a source URL and verified date.
