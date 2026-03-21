# Kazakhstan CHPP Block Extraction Report

- Created (UTC): 2026-02-24T05:20:41.756461+00:00
- Config: `C:/work/smartcities_chp_pv_sim/configs/kaz_chpp_blocks.yaml`
- Raw dir: `C:/work/smartcities_chp_pv_sim/data/interim/kaz_chpp_v3/raw_sheets`
- Out dir: `C:/work/smartcities_chp_pv_sim/data/interim/kaz_chpp_v3/blocks`

| raw_file | block_name | excel_range | shape | out_csv | out_parquet |
|---|---|---|---:|---|---|
| UnitEff_Case_1.csv | unit_eff_main | B1:O16 | (16, 15) | `UnitEff_Case_1__unit_eff_main__B1_O16.csv` | `UnitEff_Case_1__unit_eff_main__B1_O16.parquet` |
| UnitEff_Case_1.csv | rhoM_bounds | C19:O22 | (4, 14) | `UnitEff_Case_1__rhoM_bounds__C19_O22.csv` | `UnitEff_Case_1__rhoM_bounds__C19_O22.parquet` |
| UnitEff_Case_2.csv | unit_eff_main | B1:O16 | (16, 15) | `UnitEff_Case_2__unit_eff_main__B1_O16.csv` | `UnitEff_Case_2__unit_eff_main__B1_O16.parquet` |
| UnitEff_Case_2.csv | rhoM_bounds | C19:O22 | (4, 14) | `UnitEff_Case_2__rhoM_bounds__C19_O22.csv` | `UnitEff_Case_2__rhoM_bounds__C19_O22.parquet` |
| Turbine_MW.csv | heat_vs_steam_coeff | A1:G39 | (39, 8) | `Turbine_MW__heat_vs_steam_coeff__A1_G39.csv` | `Turbine_MW__heat_vs_steam_coeff__A1_G39.parquet` |
| Turbine_MW.csv | power_vs_steam_coeff | J1:P24 | (24, 8) | `Turbine_MW__power_vs_steam_coeff__J1_P24.csv` | `Turbine_MW__power_vs_steam_coeff__J1_P24.parquet` |
| Turbine_MW.csv | nomenclature_1 | R5:R12 | (8, 2) | `Turbine_MW__nomenclature_1__R5_R12.csv` | `Turbine_MW__nomenclature_1__R5_R12.parquet` |
| Turbine_MW.csv | nomenclature_2 | R14:R16 | (3, 2) | `Turbine_MW__nomenclature_2__R14_R16.csv` | `Turbine_MW__nomenclature_2__R14_R16.parquet` |

## Previews (head)

### UnitEff_Case_1.csv / unit_eff_main / B1:O16

```text
 excel_row                  B             C                  D                  E                  F                  G                  H                  I                  J                  K                  L                  M                  N                  O
         1                    av.Eff of CHP             0.8514             0.8571             0.8578             0.8506             0.8647             0.8656             0.8667             0.8644             0.8732             0.8556             0.8691             0.8527
         2  av.Eff of Boilers                               m1                 m2                 m3                 m4                 m5                 m6                 m7                 m8                 m9                m10                m11                m12
         3             0.8547            B1 0.7041186046511627   0.69943598179909  0.698865213336442 0.7047808370561957 0.6932885162484098 0.6431972966728281 0.6916886812045691 0.6935291300323925 0.6865398305084746 0.7006622019635343 0.6897785985502244 0.7030451272428756
         4 0.8986000000000001            B2 0.7402842847075406  0.735361148057403 0.7347610631848916 0.7409805313896074 0.7288979299178907 0.6762338724584104 0.7272159224645207 0.7291509023600187  0.721802611085662 0.7366503506311362 0.7252077321366932 0.7391556702239944
         5             0.8937            B3 0.7362475687103595 0.7313512775638783 0.7307544649102357 0.7369400188102517 0.7249233028796115 0.6725464186691312 0.7232504672897198 0.7251748958815365 0.7178666743014203 0.7326334502103787 0.7212532274767002 0.7351251084789493
         6             0.9046            B4 0.7452272022551092  0.740271193559678 0.7396671018885521 0.7459280978133083 0.7337648201688447 0.6807491219963031  0.732071581862236 0.7340194817214253 0.7266221255153459 0.7415690042075735 0.7300499827407663  0.744091051952621
         7 0.9037000000000001            B5  0.744485764622974 0.7395346867343369 0.7389311960830031 0.7451859628497531 0.7330347866312016 0.6800718345656193 0.7313432329525789 0.7332891948172143 0.7258991983508933 0.7408312061711081 0.7293236451501555 0.7433507446933272
         8             0.8998            B6 0.7412728682170543  0.736343157157858 0.7357422709256237 0.7419700446743476 0.7298713079680814 0.6771369223659889 0.7281870543440637    0.7301246182323 0.7227665139715987 0.7376340813464236 0.7261761822575078 0.7401427465697198
```

### UnitEff_Case_1.csv / rhoM_bounds / C19:O22

```text
 excel_row          C                                                                                         D   E   F    G  H  I  J  K  L                  M   N    O
        19 RhoM (i,m) See description in Kopanos et.al. (2018) https://doi.org/10.1016/j.enconman.2018.05.022                                                          
        20                                                                                                   m1  m2  m3   m4 m5 m6 m7 m8 m9                m10 m11  m12
        21        max                                                                                      2.85 2.7 2.5 1.31  1  1  1  1  1 1.3082602242587886 2.7 2.85
        22        min                                                                                       0.9 0.9 0.8 0.53  0  0  0  0  0 0.5329870008148462 0.9  0.9
```

### UnitEff_Case_2.csv / unit_eff_main / B1:O16

```text
 excel_row                 B             C                  D                  E                  F                  G                  H                  I                  J                  K                  L                  M                  N                  O
         1                   av.Eff of CHP 0.8231777777777778 0.8261055555555555 0.8264833333333333  0.827286111111111 0.8301666666666666               0.85 0.8425861111111111 0.8450416666666666 0.8360222222222222 0.8336611111111111 0.8324333333333334 0.8326222222222222
         2 av.Eff of Boilers                               m1                 m2                 m3                 m4                 m5                 m6                 m7                 m8                 m9                m10                m11                m12
         3            0.8547            B1 0.6989559997840348 0.6964788492188918 0.6961604952711287 0.6954849585156284 0.6930717285685606 0.6266235843137256 0.6828560773544411 0.6808718071101031 0.6882174078307328 0.6901665904744134  0.691184535298122 0.6910277329988257
         4            0.8547            B2 0.6989559997840348 0.6964788492188918 0.6961604952711287 0.6954849585156284 0.6930717285685606 0.6266235843137256 0.6828560773544411 0.6808718071101031 0.6882174078307328 0.6901665904744134  0.691184535298122 0.6910277329988257
         5            0.8937            B3 0.7308493939475744 0.7282592108891116 0.7279263304361855  0.727219968907707 0.7246966231680386 0.6552164470588236 0.7140148313228784 0.7119400187367488 0.7196207995534409  0.721658923490094 0.7227233171825572 0.7225593599871891
         6            0.8937            B4 0.7308493939475744 0.7282592108891116 0.7279263304361855  0.727219968907707 0.7246966231680386 0.6552164470588236 0.7140148313228784 0.7119400187367488 0.7196207995534409  0.721658923490094 0.7227233171825572 0.7225593599871891
         7            0.8937            B5 0.7308493939475744 0.7282592108891116 0.7279263304361855  0.727219968907707 0.7246966231680386 0.6552164470588236 0.7140148313228784 0.7119400187367488 0.7196207995534409  0.721658923490094 0.7227233171825572 0.7225593599871891
         8            0.8937            B6 0.7308493939475744 0.7282592108891116 0.7279263304361855  0.727219968907707 0.7246966231680386 0.6552164470588236 0.7140148313228784 0.7119400187367488 0.7196207995534409  0.721658923490094 0.7227233171825572 0.7225593599871891
```

### UnitEff_Case_2.csv / rhoM_bounds / C19:O22

```text
 excel_row          C                                                                                         D   E   F    G  H  I  J  K  L                  M   N    O
        19 RhoM (i,m) See description in Kopanos et.al. (2018) https://doi.org/10.1016/j.enconman.2018.05.022                                                          
        20                                                                                                   m1  m2  m3   m4 m5 m6 m7 m8 m9                m10 m11  m12
        21        max                                                                                      2.85 2.7 2.5 1.31  1  1  1  1  1 1.3082602242587886 2.7 2.85
        22        min                                                                                       0.9 0.9 0.8 0.53  0  0  0  0  0 0.5329870008148462 0.9  0.9
```

### Turbine_MW.csv / heat_vs_steam_coeff / A1:G39

```text
 excel_row                                                                                                                      A        B        C        D        E       F       G
         1 Coefficients, ranges of values and definitions of linear equations in the graph of heat load by x and steam flow by y.                                                    
         2                                                                                    Lines at heating water temperature:     k_HQ     b_HQ     H_lb     H_ub    Q_lb    Q_ub
         3                                                                                                                  75oС  1.256634  23.4163        0 18.89415  23.908 47.1593
         4                                                                                                                        1.793944  13.2643 18.89415 45.98765 47.1593 95.7635
         5                                                                                                                         2.63428 -25.3809 45.98765  68.0785 95.7635 153.957
         6                                                                                                                          2.8508 -40.1205  68.0785   79.368 153.957 186.141
         7                                                                                                                         2.85806 -40.6973   79.368   87.963 186.141 210.706
         8                                                                                                                         2.65478  -22.816   87.963  115.574 210.706 284.007
```

### Turbine_MW.csv / power_vs_steam_coeff / J1:P24

```text
 excel_row                                                                                                        J       K        L        M        N       O       P
         1 Coefficients, ranges and definitions of linear equations in the graph of power by x and steam flow by y.                                                   
         2                                                                      Lines at heating water temperature:    k_EH     b_EH     E_lb     E_ub    Q_lb    Q_ub
         3                                                                                             Kond.regime  2.93142  23.3826        0  30.9203 23.3826 114.023
         4                                                                                             Kond.regime  3.30955  11.6907  30.9203  69.6201 114.023 242.102
         5                                                                                             Kond.regime  3.77379 -20.6297  69.6201  111.217 242.102  399.08
         6                                                                                             Kond.regime  5.55876 -219.149  111.217  120.339  399.08 449.787
         7                                                                                                    75deg 3.70277  26.1948        0 51.74639 26.0099   217.8
         8                                                                                                    75deg  3.8989   16.046 51.74639 76.34185   217.8 313.695
```

### Turbine_MW.csv / nomenclature_1 / R5:R12

```text
 excel_row                         R
         5 Nomenclatures Description
         6          lb = lower bound
         7          ub = upper bound
         8                     x = E
         9                     y = H
        10                     z = Q
        11         H = k_HQ*Q + b_HQ
        12         E = k_EH*Q + b_EH
```

### Turbine_MW.csv / nomenclature_2 / R14:R16

```text
 excel_row                      R
        14 Q - inlet steam energy
        15     E- Electric Energy
        16          H-Heat energy
```

