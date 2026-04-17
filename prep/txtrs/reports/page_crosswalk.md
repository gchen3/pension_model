# TXTRS Page Crosswalk

This note records confirmed printed-page to PDF-page mappings for the highest-
value TXTRS source references used in prep work.

## Texas TRS Valuation 2024

| Source reference | Printed page | PDF page |
| --- | --- | --- |
| Table 2 `Summary of Cost Items` | `17` | `24` |
| Table 3b `Calculation of Covered Payroll` | `19` | `26` |
| Table 8a `Change in Plan Net Assets` | `26` | `33` |
| Table 15a `Statistical Information - Active and Inactive Members` | `38` | `45` |
| Table 15b `Statistical Information - Retired Members` | `39` | `46` |
| Table 17 `Distribution of Active Members by Age and by Years of Service` | `41` | `48` |
| Table 20 `Retirees, Beneficiaries, and Disabled Participants Added to and Removed from Rolls` | `44` | `51` |
| Appendix 2 actuarial assumptions overview / investment return / active mortality | `60` | `67` |
| Appendix 2 termination rates | `61` | `68` |
| Appendix 2 disability rates | `62` | `69` |
| Appendix 2 retirement-rate adjustments and salary increase assumptions | `63` | `70` |
| Appendix 2 post-retirement mortality / `Scale UMP 2021` | `64` | `71` |
| Appendix 2 payroll growth for funding of UAAL | `66` | `73` |
| Appendix 2 `NEW ENTRANT PROFILE` | `69` | `76` |

## Notes

- Printed pages are the primary human-facing citations for prep notes.
- PDF pages are the viewer/file page numbers needed for extraction tooling.
- The key TXTRS `valuation_inputs` are split across multiple tables:
  participant counts and gross normal cost are in Table 2, covered payroll is
  in Table 3b, and the current benefit-payment anchor is directly visible in
  Table 8a.
