# Targeting Constraints Playbook

## Targeting Dimensions

### Geographic Targeting
- **DMA (Designated Market Area)**: Preferred for US campaigns, 210 DMAs available
- **Metro**: City-level, more precise, fewer available impressions
- **State/Country**: Broad reach plays, branding
- **Exclusions always override inclusions**

### Demographic Targeting
- Age brackets: 18-24, 25-34, 35-44, 45-54, 55-64, 65+
- Gender: M, F, Unknown (unknown = 30-40% of supply, don't exclude)
- Income: HHI tiers (top 25%, 26-50%, 51-75%, bottom 25%)

### Device Targeting
- Desktop, Mobile Web, Mobile App, CTV/OTT, Tablet
- OS: iOS, Android, Windows, macOS, Roku, FireTV, AppleTV

### Audience Targeting
- **First-party**: CRM match, pixel retargeting, lookalike
- **Third-party**: DMP segments, contextual
- **Contextual**: IAB categories (preferred over behavioral post-iOS14)

## Broadening Targeting (Under-Delivery Playbook)
When pacing severely under target (pacing_rate < 0.70):

1. **Step 1 - Device**: Add tablet/CTV if desktop/mobile only
2. **Step 2 - Geography**: Expand from metro to DMA, DMA to state  
3. **Step 3 - Demographic**: Relax age restrictions (widen ±1 bracket each side)
4. **Step 4 - Audience**: Add lookalike tier 2 (if only tier 1 active)
5. **Step 5 - Supply**: Add Tier 2 supply sources (see supply_quality_policy.md)

Do not broaden more than 2 steps per 6-hour window without campaign manager review.

## Tightening Targeting (Quality Playbook)
When quality signals degrade (high CPA, low viewability, fraud signals):

1. **Step 1 - Supply**: Move to curated/PMP deals, remove open exchange
2. **Step 2 - Device**: Restrict to highest-quality device (often desktop + CTV)
3. **Step 3 - Viewability**: Apply >60% viewability filter
4. **Step 4 - Geography**: Focus on Tier 1 markets only
5. **Step 5 - Brand safety**: Apply category exclusions (gambling, adult, news for sensitive advertisers)

## Frequency Capping
- **Standard**: 3 impressions per user per day, 10 per week
- **Retargeting**: 5 per day, 20 per week  
- **CTV**: 2 per day (longer ad formats, fatigue faster)
- **Prospecting upper funnel**: 1-2 per day (efficiency focus)
- When reach is limited by frequency cap: increase cap before broadening geo

## Audience Segment Priorities
| Segment Type | Bid Priority | Expected CVR |
|-------------|--------------|--------------|
| Cart abandoners (1d) | Highest (2.0x) | 8-15% |
| Site visitors (7d) | High (1.5x) | 3-7% |
| Past purchasers | High (1.5x) | 5-10% |
| Email list match | Medium-high (1.3x) | 2-5% |
| Lookalike tier 1 | Medium (1.0x) | 0.5-2% |
| Lookalike tier 2 | Medium-low (0.8x) | 0.2-1% |
| Contextual only | Low (0.7x) | 0.1-0.5% |

## Suppression Lists
Always apply unless explicitly overridden:
- Recent converters (30d) — exclude from conversion campaigns, include in upsell
- Churned customers (>180d no activity) — test re-engagement with 0.6x bid
- Competitor employee domains — exclude
- Internal IPs — always exclude
