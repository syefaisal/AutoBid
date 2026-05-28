# Supply & Inventory Quality Policy

## Supply Source Tiers

### Tier 1 (Premium — Default Allowlist)
Direct publisher relationships and top-tier SSPs:
- Google Ad Manager (GAM) 
- Magnite (former Rubicon)
- PubMatic
- Index Exchange  
- OpenX
- TripleLift (native)
- SpotX/Magnite CTV

Characteristics: Low fraud risk, high viewability (>65%), brand-safe by default.

### Tier 2 (Curated — Use for Scale)
Quality exchanges with additional filters required:
- Xandr (AppNexus)
- Sovrn
- Sharethrough
- Verizon Media (Yahoo)

Require: ads.txt verification, minimum 50% viewability filter, IVT < 5%.

### Tier 3 (Open — Under-Delivery Only)
- Long-tail exchanges
- Apply only when pacing_rate < 0.65 and all Tier 1+2 exhausted
- Require: DV/IAS brand safety + fraud pre-bid filtering mandatory
- Budget cap: max 15% of daily spend from Tier 3 sources

## Fraud Prevention

### Pre-bid Filtering (Always On)
- Invalid Traffic (IVT) filtering: require GIVT+SIVT filter on all buys
- Domain fraud: reject non-ads.txt compliant inventory
- App fraud: reject non-app-ads.txt compliant app inventory
- Minimum viewability: 40% (50% for brand campaigns)

### Post-bid Monitoring
Alert thresholds (triggers review):
- IVT rate > 8% on any placement → immediate pause + investigation
- Viewability < 35% on placement → reduce bid -40% or exclude
- CTR > 5% (suspicious bot behavior) → flag + manual review
- Suspicious domain patterns (made-for-advertising) → block list

## Curated Deal Priority
When available, prefer curated/PMP deals over open exchange:
```
Priority Order:
1. Preferred deals (fixed price, guaranteed volume)
2. Private Marketplace (PMP) / Invitation-only auctions
3. Open Auction with Tier 1 supply
4. Open Auction with Tier 2 supply  
5. Open Auction with Tier 3 (emergency under-delivery only)
```

## CTV/OTT Supply Policy
CTV inventory has different quality standards:
- Only accredited MRC vendors for measurement
- Completion rate must exceed 70% or pause placement
- Fraudulent CTV is emerging threat: require ACR + IP validation
- Premium CTV (Hulu, Peacock, Paramount+): apply 1.3x bid premium
- FAST (Pluto, Tubi): apply 0.9x modifier, monitor brand safety closely

## Creative-to-Supply Matching
- HTML5/VAST creatives: compatible with display + video exchanges
- VPAID: declining support, move to OMID where possible
- Native: TripleLift, Sharethrough preferred
- Rich media: requires per-publisher approval, avoid on programmatic open

## Supply Diversity Rule
No single supply source should represent >40% of campaign spend.
If concentration exceeds this, redistribute bids to diversify.
