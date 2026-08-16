const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  ExternalHyperlink,
  Footer,
  HeadingLevel,
  PageBreak,
  PageNumber,
  PageOrientation,
  Packer,
  Paragraph,
  SectionType,
  ShadingType,
  Table,
  TableCell,
  TableLayoutType,
  TableRow,
  TextRun,
  VerticalAlignSection,
  VerticalAlignTable,
  WidthType,
} = require("docx");

const OUTPUT_DIR = path.resolve(
  __dirname,
  "..",
  "reports",
  "literature_review_assessment_20260811",
);

const ITEM_3_PATH = path.join(
  OUTPUT_DIR,
  "MDS650_Assessment_Item_3_Literature_Review.docx",
);
const ITEM_2_PATH = path.join(
  OUTPUT_DIR,
  "MDS650_Assessment_Item_2_Literature_Review.docx",
);

const COLORS = {
  navy: "17365D",
  blue: "2F75B5",
  paleBlue: "DDEBF7",
  veryPaleBlue: "EDF4F8",
  paleGrey: "F2F2F2",
  midGrey: "7F8C8D",
  line: "B4C6E7",
  warning: "FFF2CC",
  white: "FFFFFF",
  black: "000000",
  hyperlink: "0563C1",
};

const A4 = { width: 11906, height: 16838 };
const BODY_MARGINS = {
  top: 1440,
  right: 1440,
  bottom: 1440,
  left: 2160,
  header: 720,
  footer: 720,
};
const TABLE_MARGINS = {
  top: 720,
  right: 720,
  bottom: 720,
  left: 1440,
  header: 540,
  footer: 540,
};

const title =
  "Point-in-Time Option-Market Information for Forecasting Next-30-Minute Realized Variance: A Critical Literature Review";

const metadata = {
  student: "Miguel Antonio Guerrero Quijano",
  studentId: "SPI240339",
  unit: "MDS650 Data Science Capstone Research Project",
  supervisor: "[Insert supervisor name]",
  institution: "[Insert institution name]",
  date: "11 August 2026",
};

const item3 = {
  abstract: [
    `Volatility forecasts at intraday horizons can fail for two separate reasons: the target may be measured poorly, or the model may omit information that was available when the forecast was made. This review examines whether ordinary option-state variables and trade-derived option activity can add to underlying-market controls when forecasting next-30-minute realized variance (RV30) for US equities. Searches conducted on 11 August 2026 across Crossref, OpenAlex, Google Scholar, ScienceDirect, SSRN, IDEAS/RePEc, Wiley, Springer, the ACM Digital Library, and Semantic Scholar produced a 45-record, DOI-checked candidate pool. Nineteen records were retained after screening and ten complete texts were audited. The evidence falls into four themes: construction of realized-variance targets, econometric and machine-learning models, option-state and option-demand information, and chronological evaluation under noisy targets. The most transferable findings support a heterogeneous autoregressive baseline, quasi-likelihood loss (QLIKE), and nested comparisons on identical forecast origins. No reviewed paper jointly tests RV30, point-in-time ordinary option state, and trade-derived activity. Several studies also leave transformation chronology, data access, or release timing unclear. These gaps support a leakage-controlled capstone design that changes the information set while holding the target, model, and eligible origins fixed.`,
  ],
  introduction: [
    `Realized variance summarizes the variation observed within a trading period by adding squared intraday returns. It is useful for risk monitoring and forecasting because it is built from prices rather than inferred only from a parametric model. At a 30-minute horizon, however, measurement choices and data timing become especially important. A forecast can appear accurate because future information entered a feature, because the target was constructed inconsistently, or because the comparison used different rows for different models. Patton (2011) shows that even the ranking of realized-variance estimators can change with the proxy and loss function used.`,
    `The capstone addresses a narrower question: Does adding conventional point-in-time option-market information and available point-in-time trading activity to underlying-market controls improve out-of-sample prediction of RV30 for US equities, measured primarily by QLIKE on common eligible forecast origins? Conventional option state includes measures such as at-the-money implied volatility, which reflects volatility embedded in ordinary option prices. Trade-derived activity instead describes observed option transactions, including their count, premium, imbalance, and concentration. The distinction matters because price state and trading activity are different information sources.`,
    `The review covers data construction, feature engineering, statistical and machine-learning models, temporal validation, loss functions, and reproducibility. It gives greatest weight to ten studies whose complete text was audited, while keeping every conclusion within the market, horizon, and source version examined. Sections 2 and 3 explain the selection method and thematic evidence. Sections 4 to 6 evaluate limitations, identify gaps, and translate the evidence into the capstone design.`,
  ],
  methodology: [
    `The search combined discovery with targeted verification. Queries covered “intraday realized volatility forecasting,” “options-driven volatility forecasting,” “option order flow realized volatility,” “QLIKE forecast evaluation,” and “machine learning realized volatility forecasting.” Crossref and OpenAlex supplied DOI and bibliographic discovery; publisher sites and research repositories supplied full text. The recent search window was 2024 to 2026, supplemented by older method and mechanism papers when relevant. Broad database result totals were not treated as screened studies because those searches were inclusive.`,
    `A paper was retained when it informed at least one material element of the project: high-frequency target construction, ordinary option state, trade-derived activity, a credible forecasting baseline, chronological out-of-sample testing, or variance-forecast evaluation. Records that lacked a connection, duplicated a DOI, or offered only unverified claims were excluded from the synthesis. This produced 45 DOI-checked candidates, 19 retained records, and ten complete-text audits. The process is a structured methodological review, not a PRISMA review.`,
    `Quality was judged on five project-specific dimensions: direct fit to RV30 and the option information sets (45%), similarity of data and horizon (15%), temporal validity (15%), method fit (15%), and evidence traceability (10%). The score ranks usefulness for this capstone, not universal paper quality. Five studies form the core portfolio: Kambouroudis et al. (2021) for incremental implied-volatility evidence, Michael et al. (2025) for option-feature design, Puke and Schweikert (2026) for QLIKE-aligned estimation, Ni et al. (2008) for the trade-activity mechanism, and Patton (2011) for target and loss validity. Source-version and access limitations remained attached to each claim.`,
  ],
  theme1: [
    `Target construction is not a neutral preprocessing step. Patton (2011) compared many realized-variance estimators for IBM and showed that rankings depend on sampling frequency, market microstructure noise, the latent-process approximation, and the evaluation loss. His study supports sensitivity analysis but is an estimator-ranking exercise, not a future-volatility forecast. Caporin et al. (2024) used one-minute data for the Dow Jones index and 26 constituents, decomposing daily variance by sign, magnitude, and time of day. Reconciliation improved selected daily forecasts, especially under QLIKE, yet the gain changed with horizon and metric. Zhang et al. (2024) used five-minute Shanghai index data and reported better fixed-holdout forecasts after adding positive and negative jump components to an LSTM. Its single-market design and unclear normalization scope limit transfer. None of these targets is RV30, so their value lies in measurement discipline and candidate features rather than expected local performance.`,
  ],
  theme2: [
    `A heterogeneous autoregressive (HAR) model, which combines recent, weekly, and monthly variance lags, is the common benchmark across the forecasting studies. The option papers add a more relevant layer. Kambouroudis et al. (2021) found that implied-volatility information improved daily QLIKE relative to HAR across ten equity indices, although the best extension differed by market. Michael et al. (2025) built richer option surfaces and model-derived option states for 66 stocks. Their results were mixed across Elastic Net, LASSO, XGBoost, and the chosen loss, which argues against a single model winner. Broader comparisons point in the same direction. Kılıç (2025) found no universal machine-learning advantage over HAR and regime-switching specifications for the S&P 500. Omer et al. (2026) reported gains for tree models in crude oil, but the market differs and forward imputation may not have been origin-safe. Zhang et al. (2025) found short-horizon gains from a graph neural network, while one monthly MSE comparison worsened and added graph depth did not help. Puke and Schweikert (2026) instead changed the estimation loss and obtained much more consistent QLIKE improvements than MSE improvements. Complexity helps in some settings, not as a general rule.`,
  ],
  theme3: [
    `System design determines whether a promising feature could have existed at forecast time. Ni et al. (2008) linked non-market-maker option demand to subsequent underlying volatility, providing the clearest mechanism for trade-derived activity. The evidence is in-sample, based on daily data from 1990 to 2001, and does not compare nested out-of-sample forecasts. Kambouroudis et al. (2021) used rolling evaluation, but the availability of an overnight return depends on the unspecified forecast origin. Michael et al. (2025) reported train, validation, and test proportions without establishing chronology or train-only fitting for every surface transformation. Most datasets also require licensed vendors, and code is usually unavailable. Puke and Schweikert (2026), with public realized-variance data and replication code, are the notable exception. A credible RV30 pipeline therefore needs explicit event-time fields, point-in-time filters, immutable source records, and train-only feature transformations. Late-arriving option events must be excluded or assigned to later origins, and the feature store must preserve the cutoff used for each prediction. A cloud pipeline alone does not establish point-in-time validity; lineage and timestamp rules do.`,
  ],
  theme4: [
    `Evaluation choices explain several apparent contradictions. QLIKE is suited to positive variance forecasts and is less sensitive than squared error to noise in the observed variance proxy, provided the proxy conditions are met (Patton, 2011). Caporin et al. (2024) showed that the same reconciliation method can look stronger under QLIKE than under MSE. Puke and Schweikert (2026) further showed that fitting a HAR model with the loss used for evaluation can improve that loss without producing equally consistent MSE gains. Diebold–Mariano tests and model confidence sets appear in several papers, but formal tests cannot repair leakage or unequal samples. For RV30, adjacent targets overlap, so random cross-validation would exaggerate independence. Comparisons should use chronological folds, a purge and embargo around boundaries, transformations fitted only on prior data, and identical forecast-origin rows. QLIKE should be primary, while MAE and RMSE remain interpretable secondary checks.`,
  ],
  critical: [
    `The datasets are generally sufficient for the questions the original authors asked, but they are not interchangeable with the capstone data. The strongest option-state studies use daily targets and either market-wide implied-volatility indices or a selected set of non-dividend-paying stocks. The activity study by Ni et al. (2008) covers many stocks, yet its daily range-based target and historical market structure differ sharply from a five-minute-origin RV30 panel. High-frequency studies offer closer sampling, but most contain no option information. A large row count therefore does not resolve the central transfer problem.`,
    `Reproducibility is uneven. OptionMetrics, LOBSTER, CRSP, Bloomberg, TAQ, Datastream, JoinQuant, and CBOE investor-class data are restricted or incompletely documented in the reviewed papers. Exact queries, snapshots, adjustment logs, seeds, and code are often missing. Puke and Schweikert (2026) provide the clearest reproducible package, while Caporin et al. (2024) were audited through a preprint whose line-by-line equivalence with the published version was not established. These conditions do not invalidate the papers, but they lower confidence in exact replication and make provider-specific timing assumptions non-transferable.`,
    `Benchmark quality is stronger than model-selection quality. HAR appears repeatedly and provides a transparent persistence benchmark. By contrast, deep networks, graph models, regime-switching specifications, and tree ensembles are tested with different markets, features, tuning procedures, and losses. Kılıç (2025) and Michael et al. (2025) both show that rankings change by metric or specification. Zhang et al. (2024) average stochastic runs but do not fully document nested tuning, and Omer et al. (2026) leave a possible future-aware imputation path. These studies justify challengers and ablations, not an advance decision that machine learning will win.`,
    `Real-world timing is the largest unresolved assumption. A feature must be observable before the origin, not merely dated on the same trading day. Several papers lag variables, but few audit vendor publication timestamps, revision vintages, or train-only transformations in enough detail for point-in-time reconstruction. Trading-profit exercises add further assumptions about costs and liquidity, yet the capstone question concerns forecast loss rather than a trading strategy. Generalization should therefore be tested across assets, session periods, and volatility regimes, with negative and null results retained.`,
  ],
  gaps: [
    `Five gaps remain. First, no audited study evaluates next-30-minute realized variance for US equities while combining one-minute underlying data with point-in-time option information. Second, the literature does not cleanly separate ordinary option state from trade-derived activity in a nested B0-to-B1-to-B2 out-of-sample comparison. Ni et al. (2008) motivate the activity mechanism, while Michael et al. (2025) motivate ordinary option features, but neither supplies the required incremental test. Third, source timing, data snapshots, transformation fitting, and public replication are often incomplete, leaving avoidable leakage and reproducibility risk. Fourth, reported model gains vary by market, horizon, loss, and regime; complex models are rarely compared under exactly the same eligible origins and target definition. Fifth, association between option demand and future volatility is often treated as predictive value, although it does not prove incremental forecast improvement. The capstone matters because it addresses these gaps as one controlled data-science problem rather than borrowing an effect size from a daily or non-equity study.`,
  ],
  implications: [
    `The literature shapes the capstone as an incremental-information experiment. RV30 will be computed from the observed origin close and the next 30 one-minute closes, producing 30 log returns. B0 will contain underlying-market controls; B1 will add ordinary point-in-time option state; and B2 will add compact trade-derived activity. These are information sets, not algorithms. Each comparison will therefore hold the model, target, fold, and eligible forecast origins constant.`,
    `Persistence and HAR provide transparent sanity checks. A Gamma generalized linear model is the confirmatory positive-mean model, and a fixed Gamma LightGBM specification is a nonlinear challenger rather than a route for post-result model promotion. Evaluation will use expanding temporal folds, at least a 30-minute purge and embargo around boundaries, and train-only fitting of every transform. QLIKE is primary, with MAE and RMSE reported descriptively and uncertainty clustered by trading day. This design responds directly to the timing, measurement, and unequal-sample weaknesses in the literature. It does not presume that B1 or B2 will improve forecasts.`,
  ],
  conclusion: [
    `The reviewed evidence supports disciplined comparison more strongly than it supports any particular model winner. HAR remains a credible baseline, option-implied variables can add information in daily settings, trade-derived demand has a plausible association with future volatility, and QLIKE is well suited to variance-forecast evaluation. Each conclusion has a boundary: none of the ten studies reproduces the exact RV30, point-in-time, nested-information-set problem. The capstone is therefore relevant because it joins these separate strands in one chronological and auditable design. Its contribution will come from isolating the incremental information in B1 and B2 on common origins, while reporting positive, negative, or null evidence with the same standard.`,
  ],
};

const item2 = {
  introduction: [
    `The capstone asks whether information from the option market improves forecasts of next-30-minute realized variance (RV30) for US equities. The question is narrower than “Which model predicts volatility best?” It separates three information sets: underlying-market controls (B0), ordinary option state such as at-the-money implied volatility (B1), and trade-derived option activity (B2). The purpose of this review is to determine what existing research supports for the target, features, models, and evaluation design, and where direct evidence is missing.`,
    `A structured search produced 45 DOI-checked candidates, retained 19 records, and audited ten complete texts. The five core papers were selected for distinct roles rather than treated as interchangeable winners: Kambouroudis et al. (2021) test incremental implied-volatility information, Michael et al. (2025) develop option-state features, Puke and Schweikert (2026) study QLIKE-aligned estimation, Ni et al. (2008) motivate trade-activity information, and Patton (2011) establishes measurement and loss principles. Five additional studies broaden the comparison across decompositions, econometric models, machine learning, and graph methods. The review is organized by target construction, option information, model choice, and experimental design.`,
  ],
  targetTheme: [
    `Realized variance is normally constructed by adding squared intraday log returns. That definition sounds straightforward, but the sampling interval, price type, trading session, and treatment of noise can change both the target and the apparent ranking of forecasts. Patton (2011) makes this point directly. Using IBM trades and quotes at frequencies from one second to one day, he shows that estimator rankings vary with the latent-process approximation and the loss used for comparison. His result is methodological: it supports prespecifying the estimator and checking sensitivity. It does not show which variables forecast future RV30.`,
    `The recent high-frequency papers illustrate different construction choices. Caporin et al. (2024) build daily open-to-close variance from one-minute returns for the Dow Jones index and 26 continuously available constituents. They decompose variance by sign, magnitude, and time of day, then reconcile component forecasts. The reported improvement is strongest in selected QLIKE comparisons and is not uniform across horizons or MSE. Puke and Schweikert (2026) use both one- and five-minute realized measures for 28 Dow Jones stocks and compare HAR specifications estimated by MSE or QLIKE. Their central contribution is loss alignment rather than a new data source.`,
    `Zhang et al. (2024) take another path, separating five-minute Shanghai index variation into continuous, positive-jump, and negative-jump components. The signed-jump LSTM improves the authors’ fixed holdout relative to the same architecture without jumps, but the evidence comes from one index and the chronology of normalization and tuning is incomplete. Zhang et al. (2025) also aggregate five-minute returns to daily targets before applying graph models across stocks. These studies offer useful feature and dependence ideas, yet none uses the capstone target. RV30 is a forward 30-minute quantity built from 31 consecutive prices, whereas the reviewed studies mainly forecast a day, week, or month. Target similarity is therefore partial even when raw data arrive every one or five minutes.`,
  ],
  optionTheme: [
    `Option prices carry a market view of future volatility. Kambouroudis et al. (2021) provide the clearest incremental test in the audited set. Across ten international equity indices, they add implied volatility, leverage, overnight returns, and volatility-of-realized-volatility to HAR. Implied-volatility specifications improve QLIKE relative to HAR in every market, but the best combination of additional variables differs across indices. The evidence supports testing an ordinary option-state feature. It does not establish that a daily index result will hold for individual-stock RV30, and the implied-volatility horizon is much longer than 30 minutes.`,
    `Michael et al. (2025) move closer to an asset-level feature design. They combine one-minute equity prices with daily option surfaces, volume, VIX, and partially calibrated Heston and Bates states for 66 non-dividend-paying NYSE stocks. Elastic Net, LASSO, and XGBoost are compared across nested feature groups. Rich option features improve selected out-of-sample measures, but the ranking changes with model and loss. The split is reported as 60% training, 10% validation, and 30% test without enough detail to confirm chronology or train-only surface transformations. Licensed datasets and missing replication code also restrict independent reconstruction. The paper is consequently strong evidence for what B1 can contain, not for a guaranteed effect size.`,
    `Trade-derived activity is a separate hypothesis. Ni et al. (2008) construct vega-weighted non-market-maker net option demand for more than 2,000 stocks and find positive associations with realized volatility over the next one to five days. The association is stronger around earnings, when information trading is more plausible. This is useful mechanism evidence for B2 variables such as transaction count, premium imbalance, repeated-contract share, and concentration. Still, the study uses pooled in-sample regressions, historical daily data, and a range-based volatility target. It neither runs chronological out-of-sample forecasts nor compares B2 against a fully specified B1 on common rows. Ordinary option volume in Michael et al. is also not equivalent to unusual or informed activity. The capstone must keep price state, transaction activity, and claims about trader intent separate.`,
  ],
  modelTheme: [
    `The model literature gives one consistent recommendation: retain a simple, strong baseline. HAR appears in nearly every audited forecasting study because it summarizes short-, medium-, and longer-memory persistence with few parameters. Caporin et al. (2024), Kambouroudis et al. (2021), Michael et al. (2025), Puke and Schweikert (2026), and Zhang et al. (2025) all use HAR or a close extension. This repetition is more informative for model selection than any single reported ranking. A method that cannot beat persistence and HAR on identical origins has weak practical justification.`,
    `Comparisons between econometric and machine-learning models are less settled. Kılıç (2025) studies daily S&P 500 variance across several market regimes using ARFIMA, HAR, threshold and smooth-transition HAR, a Markov-switching HAR, XGBoost, and multiple neural networks. A smooth-transition HAR leads selected pooled losses, but the QLIKE model confidence set remains broad and expanded predictors do not produce a universal machine-learning advantage. The paper also leaves possible test-sample scaling leakage and target-transformation inconsistencies unresolved. It supports nonlinear econometric challengers and careful regime analysis, not a claim that either econometrics or machine learning dominates.`,
    `Omer et al. (2026) compare HAR, regularized regression, trees, forests, and neural networks for crude-oil variance using uncertainty and exchange-rate predictors. Trees improve selected relative errors, but the market is different, QLIKE is absent, and forward imputation may have used unavailable information. Zhang et al. (2024) report gains from a signed-jump LSTM, while Zhang et al. (2025) report short-horizon graph-network gains but little benefit from additional graph depth and a worse monthly MSE in one comparison. Puke and Schweikert (2026) show that changing the fitting loss can matter more consistently than adding architecture. These results favour a restrained model set: transparent persistence and HAR checks, a positive-mean confirmatory model, and one fixed nonlinear challenger. Deep learning or graph models should enter only through a prespecified, sample-appropriate ablation.`,
  ],
  evaluationTheme: [
    `A fair experiment must preserve time order and evaluate every information set on the same rows. The reviewed papers use several reasonable designs: fixed terminal holdouts, rolling windows, annual expanding origins, and monthly recalibration. Their safeguards are not equivalent. Caporin et al. (2024), Kambouroudis et al. (2021), Puke and Schweikert (2026), and Zhang et al. (2025) provide clear chronological structures. Michael et al. (2025) give split proportions but not enough timing detail. Ni et al. (2008) provide mechanism evidence without an out-of-sample benchmark. These differences partly explain why results should not be ranked by headline accuracy alone.`,
    `QLIKE is the most suitable primary loss in this corpus because the target is positive variance and observed realized variance is itself a noisy proxy. Patton (2011) supplies the measurement rationale. Caporin et al. (2024) and Puke and Schweikert (2026) show empirically that conclusions can differ between QLIKE and squared error. MAE and RMSE remain useful because readers understand their scale and tail sensitivity, but they answer different questions. Diebold–Mariano tests and model confidence sets add formal comparison, although they cannot correct a leaky feature or an unequal sample.`,
    `Reproducibility is the weakest shared element. Most studies depend on commercial data, omit immutable query snapshots, and do not publish complete code. Puke and Schweikert (2026) are the main exception with public realized-variance data and a replication repository. For RV30, the risk is sharper because adjacent targets overlap and option fields can arrive after the nominal timestamp. Random cross-validation is unsuitable. The capstone needs expanding folds, a 30-minute purge and embargo at boundaries, train-only transformations, explicit point-in-time filters, and paired comparisons using identical origin identifiers. Those controls are part of the statistical method, not merely engineering detail.`,
  ],
  gaps: [
    `The literature leaves four connected gaps. The first is target alignment. No audited paper forecasts the exact next-30-minute realized variance of US equities while using one-minute prices and option data available at each five-minute origin. Daily or multi-day findings cannot supply an expected RV30 effect size.`,
    `The second gap is information-set identification. Kambouroudis et al. (2021) and Michael et al. (2025) support ordinary option-state features, while Ni et al. (2008) supports a trade-activity mechanism. No study estimates the incremental B2-versus-B1 effect while also retaining B1-versus-B0 on the same forecast origins. Without that nesting, an apparent activity gain may simply recover information already present in option prices.`,
    `The third gap is point-in-time reproducibility. Source timestamps, revision vintages, missingness rules, surface transformations, and dataset snapshots are frequently underreported. This matters more at an intraday horizon, where a delay of minutes can reverse whether a feature is legitimate. The fourth gap is controlled model comparison. Machine-learning gains vary by market, horizon, loss, and tuning design, and null findings are often less prominent than winners.`,
    `The capstone addresses these gaps through one registered question: whether B1 adds to B0 and whether B2 adds to B1 for RV30. The target, common-origin sample, temporal folds, Gamma generalized linear confirmatory model, fixed LightGBM challenger, QLIKE primary loss, and paired day-level inference are held constant. The contribution is therefore an auditable estimate of incremental information, not a search for the most impressive algorithm or a claim about trading profitability.`,
  ],
  conclusion: [
    `Existing research supplies useful pieces of the RV30 problem but not the complete design. High-frequency studies clarify target construction; HAR provides a stable benchmark; option-implied variables support the B1 hypothesis; option demand motivates B2; and Patton (2011) together with Puke and Schweikert (2026) supports QLIKE and loss-aware evaluation. The evidence also exposes limits: daily horizons, restricted datasets, incomplete timing records, and model rankings that change by metric or market. The capstone contributes by joining these pieces in a point-in-time, nested, common-origin experiment. Its value does not depend on a positive result. A carefully estimated null or negative B2 increment would still resolve a question that the reviewed literature leaves open.`,
  ],
};

const references = [
  {
    key: "Caporin et al. (2024)",
    prefix:
      "Caporin, M., Di Fonzo, T., & Girolimetto, D. (2024). Exploiting intraday decompositions in realized volatility forecasting: A forecast reconciliation approach. ",
    italic: "Journal of Financial Econometrics, 22",
    suffix: "(5), 1759–1784. ",
    doi: "https://doi.org/10.1093/jjfinec/nbae014",
  },
  {
    key: "Kambouroudis et al. (2021)",
    prefix:
      "Kambouroudis, D. S., McMillan, D. G., & Tsakou, K. (2021). Forecasting realized volatility: The role of implied volatility, leverage effect, overnight returns, and volatility of realized volatility. ",
    italic: "Journal of Futures Markets, 41",
    suffix: "(10), 1618–1639. ",
    doi: "https://doi.org/10.1002/fut.22241",
  },
  {
    key: "Kılıç (2025)",
    prefix: "Kılıç, R. (2025). ",
    italic:
      "Linear and nonlinear econometric models against machine learning models: Realized volatility prediction",
    suffix:
      " (Finance and Economics Discussion Series 2025-061). Board of Governors of the Federal Reserve System. ",
    doi: "https://doi.org/10.17016/FEDS.2025.061",
  },
  {
    key: "Michael et al. (2025)",
    prefix:
      "Michael, N., Cucuringu, M., & Howison, S. (2025). Options-driven volatility forecasting. ",
    italic: "Quantitative Finance, 25",
    suffix: "(3), 443–470. ",
    doi: "https://doi.org/10.1080/14697688.2025.2454623",
  },
  {
    key: "Ni et al. (2008)",
    prefix:
      "Ni, S. X., Pan, J., & Poteshman, A. M. (2008). Volatility information trading in the option market. ",
    italic: "The Journal of Finance, 63",
    suffix: "(3), 1059–1091. ",
    doi: "https://doi.org/10.1111/j.1540-6261.2008.01352.x",
  },
  {
    key: "Omer et al. (2026)",
    prefix:
      "Omer, T., Månsson, K., Sjölander, P., & Uddin, G. S. (2026). Machine learning approaches to forecast the realized volatility of crude oil prices. ",
    italic: "Journal of Forecasting, 45",
    suffix: "(4), 1633–1651. ",
    doi: "https://doi.org/10.1002/for.70107",
  },
  {
    key: "Patton (2011)",
    prefix:
      "Patton, A. J. (2011). Data-based ranking of realised volatility estimators. ",
    italic: "Journal of Econometrics, 161",
    suffix: "(2), 284–303. ",
    doi: "https://doi.org/10.1016/j.jeconom.2010.12.010",
  },
  {
    key: "Puke and Schweikert (2026)",
    prefix:
      "Puke, M., & Schweikert, K. (2026). Coherent forecasting of realized volatility. ",
    italic: "Journal of Forecasting, 45",
    suffix: "(4), 1714–1729. ",
    doi: "https://doi.org/10.1002/for.70114",
  },
  {
    key: "Zhang et al. (2025)",
    prefix:
      "Zhang, C., Pu, X., Cucuringu, M., & Dong, X. (2025). Forecasting realized volatility with spillover effects: Perspectives from graph neural networks. ",
    italic: "International Journal of Forecasting, 41",
    suffix: "(1), 377–397. ",
    doi: "https://doi.org/10.1016/j.ijforecast.2024.09.002",
  },
  {
    key: "Zhang et al. (2024)",
    prefix:
      "Zhang, Y., Song, Y., Peng, Y., & Wang, H. (2024). Volatility forecasting incorporating intraday positive and negative jumps based on deep learning model. ",
    italic: "Journal of Forecasting, 43",
    suffix: "(7), 2749–2765. ",
    doi: "https://doi.org/10.1002/for.3146",
  },
];

const comparisonRows = [
  {
    core: true,
    reference: "Core #1\nKambouroudis et al.",
    year: "2021",
    area: "B1 incremental forecast",
    dataset:
      "10 international equity indices; 5-minute RV and daily option-IV indices; 2001–2019",
    model: "HAR plus IV, leverage, overnight return, and volatility-of-RV",
    finding:
      "IV improves daily QLIKE versus HAR across all 10 markets; the best extension varies by market.",
    limitation:
      "Daily index evidence; IV horizon mismatch; forecast-origin timing unclear; no trade-derived B2.",
  },
  {
    core: true,
    reference: "Core #2\nMichael et al.",
    year: "2025",
    area: "B1 feature design",
    dataset:
      "66 NYSE non-dividend stocks; one-minute equities plus daily option surfaces and volume; 2013–2019",
    model: "Elastic Net, LASSO, XGBoost, IV-surface factors, Heston/Bates states",
    finding:
      "Rich option state improves selected loss/model combinations beyond HAR-based controls.",
    limitation:
      "Daily target; chronology and train-only transforms not fully reported; licensed data; no B2 test.",
  },
  {
    core: true,
    reference: "Core #3\nPuke & Schweikert",
    year: "2026",
    area: "QLIKE and time-valid design",
    dataset:
      "28 Dow Jones stocks; public 1- and 5-minute realized measures; common OOS 2012–2024",
    model: "HAR and semivariance HAR estimated by MSE or QLIKE",
    finding:
      "QLIKE-aligned fitting lowers QLIKE far more consistently than it lowers MSE.",
    limitation:
      "Daily horizons and no option information; direct PDF pagination partly cross-checked from other sources.",
  },
  {
    core: true,
    reference: "Core #4\nNi et al.",
    year: "2008",
    area: "B2 activity mechanism",
    dataset:
      "CBOE individual-stock options; 703,229 stock-days and 2,220 stocks; 1990–2001",
    model: "Pooled predictive and option-price-impact regressions",
    finding:
      "Non-market-maker net volatility demand is associated with higher future underlying volatility.",
    limitation:
      "In-sample association; daily range target; historical/proprietary data; no QLIKE or nested B2-vs-B1 test.",
  },
  {
    core: true,
    reference: "Core #5\nPatton",
    year: "2011",
    area: "RV target and loss validity",
    dataset:
      "IBM NYSE trades and quotes; 2,893 days; 13 frequencies and 48 simple RV estimators; 1996–2007",
    model: "Estimator ranking under random-walk and stationary AR approximations",
    finding:
      "Estimator rankings depend on proxy, sampling, latent-process assumptions, and loss; supports QLIKE and sensitivity checks.",
    limitation:
      "One stock and same-day estimator ranking, not an option-based out-of-sample forecast study.",
  },
  {
    core: false,
    reference: "Reserve #6\nZhang et al.",
    year: "2025",
    area: "Temporal and spillover robustness",
    dataset:
      "27 Dow Jones stocks plus S&P 100 check; 5-minute returns aggregated to daily RV; 2007–2021",
    model: "HAR, graph HAR, and one- to three-layer graph neural networks",
    finding:
      "Short-horizon graph gains occur, but deeper/multi-hop structure adds little and one monthly MSE worsens.",
    limitation:
      "No option information; survivor selection; proprietary data; model complexity exceeds the confirmatory design.",
  },
  {
    core: false,
    reference: "Supporting #7\nCaporin et al.",
    year: "2024",
    area: "HAR reconciliation and horizons",
    dataset:
      "Dow Jones index and 26 constituents; one-minute prices; 4,908 complete days; 2003–2022",
    model: "HAR component models with bottom-up and MinT-shrinkage reconciliation",
    finding:
      "Partial-variance reconciliation improves selected daily forecasts, especially under QLIKE, but not uniformly.",
    limitation:
      "No options or RV30; final-version equivalence not established; reporting inconsistencies remain.",
  },
  {
    core: false,
    reference: "Supporting #8\nKılıç",
    year: "2025",
    area: "Econometric vs. ML benchmark",
    dataset:
      "S&P 500; five-minute returns aggregated to daily RV; 1996–2023",
    model: "ARFIMA, HAR, threshold/regime HAR, XGBoost, and neural networks",
    finding:
      "No universal ML superiority; smooth-transition HAR leads selected pooled losses while QLIKE differences are broad.",
    limitation:
      "Preliminary paper; possible scaling leakage; one index; target/reporting inconsistencies; no B1/B2.",
  },
  {
    core: false,
    reference: "Low transfer #9\nZhang et al.",
    year: "2024",
    area: "Signed-jump deep-learning check",
    dataset:
      "Shanghai Composite; 128,016 five-minute observations across 2,667 days; 2011–2022",
    model: "LSTM plus 12 machine-learning and linear comparators",
    finding:
      "Adding positive and negative jump measures improves the reported fixed holdout for the LSTM.",
    limitation:
      "Single index; no options or QLIKE; train-only normalization and nested tuning not established.",
  },
  {
    core: false,
    reference: "Low transfer #10\nOmer et al.",
    year: "2026",
    area: "Non-equity ML comparison",
    dataset:
      "WTI crude oil; five-minute prices plus uncertainty and FX variables; 3,192 matched days; 2009–2022",
    model: "HAR, regularized regression, trees, forests, and neural networks",
    finding:
      "Trees and forests improve selected relative forecast errors over HAR at some horizons.",
    limitation:
      "Commodity mismatch; possible forward-imputation leakage; no QLIKE; restricted data and table inconsistencies.",
  },
];

const glossary = [
  ["ATM", "At the money: an option whose strike price is close to the current underlying price."],
  ["B0", "Underlying-market information available at the forecast origin, such as lagged realized variance, returns, time of day, and market state."],
  ["B1", "B0 plus ordinary point-in-time option state, primarily at-the-money implied volatility; skew and term structure are additional levels."],
  ["B2", "B1 plus trade-derived option activity, such as transaction count, premium imbalance, repeated-contract share, and concentration."],
  ["DTE", "Days to expiration of an option contract."],
  ["HAR", "Heterogeneous autoregressive model: a parsimonious volatility model using short-, medium-, and longer-memory realized-variance lags."],
  ["IV", "Implied volatility: the volatility level consistent with an observed option price under a pricing model."],
  ["OOS", "Out of sample: evaluation on later observations that were not used to fit or select the model."],
  ["PIT", "Point in time: information proven to have been available no later than the forecast origin."],
  ["QLIKE", "Quasi-likelihood loss for positive variance forecasts. Lower values indicate better forecasts; differences are not percentages."],
  ["RV", "Realized variance: the sum of squared intraday log returns over a defined interval."],
  ["RV30", "Realized variance during the 30 minutes after an origin. The project requires 31 consecutive prices, which produce 30 one-minute returns."],
  ["MAE / RMSE", "Mean absolute error and root mean squared error. RMSE gives more weight to large errors."],
  ["DM / MCS", "Diebold–Mariano test and Model Confidence Set, two tools used to compare forecast losses."],
  ["GLM / GNN", "Generalized linear model and graph neural network."],
];

function wordCount(text) {
  return (text.match(/[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:[’'\-][A-Za-zÀ-ÖØ-öø-ÿ0-9]+)*/g) || [])
    .length;
}

function sectionWordCount(paragraphs) {
  return paragraphs.reduce((total, paragraph) => total + wordCount(paragraph), 0);
}

function assertRange(label, value, min, max) {
  if (value < min || value > max) {
    throw new Error(`${label}: ${value} words; expected ${min}-${max}`);
  }
}

function documentText(sections) {
  return Object.values(sections).flat().join(" ");
}

function auditContent() {
  const item3Counts = {
    abstract: sectionWordCount(item3.abstract),
    introduction: sectionWordCount(item3.introduction),
    methodology: sectionWordCount(item3.methodology),
    thematic: sectionWordCount([
      ...item3.theme1,
      ...item3.theme2,
      ...item3.theme3,
      ...item3.theme4,
    ]),
    critical: sectionWordCount(item3.critical),
    gaps: sectionWordCount(item3.gaps),
    implications: sectionWordCount(item3.implications),
    conclusion: sectionWordCount(item3.conclusion),
  };
  assertRange("Item 3 abstract", item3Counts.abstract, 150, 200);
  assertRange("Item 3 introduction", item3Counts.introduction, 200, 250);
  assertRange("Item 3 methodology", item3Counts.methodology, 200, 250);
  assertRange("Item 3 thematic synthesis", item3Counts.thematic, 650, 700);
  assertRange("Item 3 critical analysis", item3Counts.critical, 350, 400);
  assertRange("Item 3 research gaps", item3Counts.gaps, 150, 200);
  assertRange("Item 3 implications", item3Counts.implications, 150, 200);
  assertRange("Item 3 conclusion", item3Counts.conclusion, 100, 150);

  const item2Counts = {
    introduction: sectionWordCount(item2.introduction),
    mainReview: sectionWordCount([
      ...item2.targetTheme,
      ...item2.optionTheme,
      ...item2.modelTheme,
      ...item2.evaluationTheme,
    ]),
    gaps: sectionWordCount(item2.gaps),
    conclusion: sectionWordCount(item2.conclusion),
  };
  assertRange("Item 2 introduction", item2Counts.introduction, 150, 200);
  assertRange("Item 2 main review", item2Counts.mainReview, 1200, 1500);
  assertRange("Item 2 gaps and justification", item2Counts.gaps, 200, 300);
  assertRange("Item 2 conclusion", item2Counts.conclusion, 100, 150);

  const allReports = [documentText(item3), documentText(item2)];
  const citationKeys = [
    ["Caporin", "2024"],
    ["Kambouroudis", "2021"],
    ["Kılıç", "2025"],
    ["Michael", "2025"],
    ["Ni", "2008"],
    ["Omer", "2026"],
    ["Patton", "2011"],
    ["Puke", "2026"],
    ["Zhang", "2024"],
    ["Zhang", "2025"],
  ];
  for (const [index, text] of allReports.entries()) {
    for (const [surname, year] of citationKeys) {
      if (!text.includes(surname) || !text.includes(year)) {
        throw new Error(`Item ${index === 0 ? 3 : 2} misses citation ${surname} ${year}`);
      }
    }
    const banned = [
      "delve",
      "tapestry",
      "pivotal",
      "crucial",
      "groundbreaking",
      "It is important to note",
      "It should be noted",
      "This section will discuss",
    ];
    for (const phrase of banned) {
      if (text.toLowerCase().includes(phrase.toLowerCase())) {
        throw new Error(`Item ${index === 0 ? 3 : 2} contains flagged phrase: ${phrase}`);
      }
    }
    if ((text.match(/—/g) || []).length > 1) {
      throw new Error(`Item ${index === 0 ? 3 : 2} overuses em dashes`);
    }
  }

  return { item3Counts, item2Counts };
}

function bodyParagraph(text, options = {}) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Times New Roman", size: 24, language: { value: "en-AU" } })],
    alignment: options.alignment || AlignmentType.JUSTIFIED,
    indent: options.noIndent ? undefined : { firstLine: 720 },
    spacing: { line: 360, after: 120 },
    keepLines: true,
  });
}

function heading1(text, options = {}) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [
      new TextRun({
        text,
        font: "Times New Roman",
        size: 24,
        bold: true,
        color: COLORS.navy,
        language: { value: "en-AU" },
      }),
    ],
    alignment: options.center ? AlignmentType.CENTER : AlignmentType.LEFT,
    spacing: { before: options.before ?? 200, after: 100 },
    keepNext: true,
    pageBreakBefore: options.pageBreakBefore || false,
  });
}

function heading2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [
      new TextRun({
        text,
        font: "Times New Roman",
        size: 24,
        bold: true,
        color: COLORS.black,
        language: { value: "en-AU" },
      }),
    ],
    alignment: AlignmentType.LEFT,
    spacing: { before: 160, after: 80 },
    keepNext: true,
  });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function pageNumberFooter() {
  return new Footer({
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [
          new TextRun({
            children: [PageNumber.CURRENT],
            font: "Times New Roman",
            size: 20,
            color: COLORS.midGrey,
          }),
        ],
      }),
    ],
  });
}

function coverChildren(assessmentLabel) {
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 360 },
      children: [
        new TextRun({
          text: title,
          bold: true,
          font: "Times New Roman",
          size: 34,
          color: COLORS.navy,
          language: { value: "en-AU" },
        }),
      ],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 480 },
      children: [
        new TextRun({
          text: assessmentLabel,
          bold: true,
          font: "Times New Roman",
          size: 26,
          color: COLORS.blue,
        }),
      ],
    }),
    coverLine("Student", `${metadata.student} (${metadata.studentId})`),
    coverLine("Unit", metadata.unit),
    coverLine("Supervisor", metadata.supervisor, true),
    coverLine("Institution", metadata.institution, true),
    coverLine("Date", metadata.date),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 500 },
      children: [
        new TextRun({
          text: "Before submission: replace the two highlighted title-page fields.",
          font: "Times New Roman",
          size: 20,
          italic: true,
          color: "7F6000",
          shading: { type: ShadingType.CLEAR, fill: COLORS.warning },
        }),
      ],
    }),
  ];
}

function coverLine(label, value, highlight = false) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 180 },
    children: [
      new TextRun({ text: `${label}: `, bold: true, font: "Times New Roman", size: 24 }),
      new TextRun({
        text: value,
        font: "Times New Roman",
        size: 24,
        shading: highlight ? { type: ShadingType.CLEAR, fill: COLORS.warning } : undefined,
      }),
    ],
  });
}

function keywordParagraph(words) {
  return new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: { line: 360, before: 120, after: 180 },
    children: [
      new TextRun({ text: "Keywords: ", italic: true, font: "Times New Roman", size: 24 }),
      new TextRun({ text: words, font: "Times New Roman", size: 24 }),
    ],
  });
}

function referenceParagraph(reference) {
  return new Paragraph({
    alignment: AlignmentType.LEFT,
    indent: { hanging: 720 },
    spacing: { line: 360, after: 120 },
    children: [
      new TextRun({ text: reference.prefix, font: "Times New Roman", size: 24 }),
      new TextRun({ text: reference.italic, font: "Times New Roman", size: 24, italic: true }),
      new TextRun({ text: reference.suffix, font: "Times New Roman", size: 24 }),
      new ExternalHyperlink({
        link: reference.doi,
        children: [
          new TextRun({
            text: reference.doi,
            font: "Times New Roman",
            size: 24,
            color: COLORS.hyperlink,
            underline: {},
          }),
        ],
      }),
    ],
  });
}

function glossaryTable() {
  const widths = [2100, 8600];
  const rows = [
    new TableRow({
      tableHeader: true,
      children: [
        tableCell("Term", widths[0], { header: true, fontSize: 20 }),
        tableCell("Plain-language definition", widths[1], { header: true, fontSize: 20 }),
      ],
    }),
    ...glossary.map(([term, definition], index) =>
      new TableRow({
        children: [
          tableCell(term, widths[0], {
            bold: true,
            fill: index % 2 === 0 ? COLORS.veryPaleBlue : COLORS.white,
            fontSize: 20,
          }),
          tableCell(definition, widths[1], {
            fill: index % 2 === 0 ? COLORS.veryPaleBlue : COLORS.white,
            fontSize: 20,
          }),
        ],
      }),
    ),
  ];
  return new Table({
    rows,
    width: { size: widths[0] + widths[1], type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
    borders: lightBorders(),
  });
}

function lightBorders() {
  const border = { style: BorderStyle.SINGLE, size: 4, color: COLORS.line };
  return {
    top: border,
    bottom: border,
    left: border,
    right: border,
    insideHorizontal: border,
    insideVertical: border,
  };
}

function tableCell(text, width, options = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: {
      type: ShadingType.CLEAR,
      fill: options.header ? COLORS.navy : options.fill || COLORS.white,
    },
    verticalAlign: VerticalAlignTable.CENTER,
    margins: { top: 80, bottom: 80, left: 80, right: 80 },
    children: String(text)
      .split("\n")
      .map(
        (line) =>
          new Paragraph({
            alignment: options.header ? AlignmentType.CENTER : AlignmentType.LEFT,
            spacing: { line: 220, after: 20 },
            children: [
              new TextRun({
                text: line,
                font: "Times New Roman",
                size: options.fontSize || 16,
                bold: options.header || options.bold,
                color: options.header ? COLORS.white : COLORS.black,
                language: { value: "en-AU" },
              }),
            ],
          }),
      ),
  });
}

function comparisonTable() {
  const widths = [1700, 650, 1700, 2600, 2100, 2800, 2800];
  const headers = [
    "Reference / portfolio role",
    "Year",
    "Area of application",
    "Dataset used",
    "Model employed",
    "Key finding / contribution",
    "Limitation",
  ];
  const headerRow = new TableRow({
    tableHeader: true,
    children: headers.map((header, index) =>
      tableCell(header, widths[index], { header: true, fontSize: 16 }),
    ),
  });
  const rows = comparisonRows.map((row, index) => {
    const fill = row.core
      ? COLORS.paleBlue
      : index % 2 === 0
        ? COLORS.paleGrey
        : COLORS.white;
    return new TableRow({
      cantSplit: true,
      children: [
        tableCell(row.reference, widths[0], { fill, bold: row.core, fontSize: 16 }),
        tableCell(row.year, widths[1], { fill, fontSize: 16 }),
        tableCell(row.area, widths[2], { fill, fontSize: 16 }),
        tableCell(row.dataset, widths[3], { fill, fontSize: 16 }),
        tableCell(row.model, widths[4], { fill, fontSize: 16 }),
        tableCell(row.finding, widths[5], { fill, fontSize: 16 }),
        tableCell(row.limitation, widths[6], { fill, fontSize: 16 }),
      ],
    });
  });
  return new Table({
    rows: [headerRow, ...rows],
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
    borders: lightBorders(),
  });
}

function baseDocumentOptions(titleText) {
  return {
    creator: metadata.student,
    title: titleText,
    subject: "MDS650 Literature Review",
    description:
      "Evidence-bounded draft generated from the audited literature matrices. Replace highlighted title-page fields and review before submission.",
    keywords:
      "MDS650, literature review, realized variance, RV30, option market, QLIKE, temporal validation",
    styles: {
      default: {
        document: {
          run: {
            font: "Times New Roman",
            size: 24,
            color: COLORS.black,
            language: { value: "en-AU" },
          },
          paragraph: {
            alignment: AlignmentType.JUSTIFIED,
            spacing: { line: 360, after: 120 },
          },
        },
      },
      paragraphStyles: [
        {
          id: "Heading1",
          name: "Heading 1",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { font: "Times New Roman", size: 24, bold: true, color: COLORS.navy },
          paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 0, keepNext: true },
        },
        {
          id: "Heading2",
          name: "Heading 2",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { font: "Times New Roman", size: 24, bold: true, color: COLORS.black },
          paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 1, keepNext: true },
        },
      ],
    },
  };
}

function coverSection(assessmentLabel) {
  return {
    properties: {
      type: SectionType.NEXT_PAGE,
      page: { size: { ...A4, orientation: PageOrientation.PORTRAIT }, margin: BODY_MARGINS },
      verticalAlign: VerticalAlignSection.CENTER,
    },
    children: coverChildren(assessmentLabel),
  };
}

function bodySection(children, options = {}) {
  const pageNumbers = options.startPage === undefined ? undefined : { start: options.startPage };
  return {
    properties: {
      type: SectionType.NEXT_PAGE,
      page: {
        size: { ...A4, orientation: options.orientation || PageOrientation.PORTRAIT },
        margin: options.orientation === PageOrientation.LANDSCAPE ? TABLE_MARGINS : BODY_MARGINS,
        pageNumbers,
      },
    },
    footers: { default: pageNumberFooter() },
    children,
  };
}

function item3Document() {
  const body = [
    heading1("Abstract", { center: true, before: 0 }),
    ...item3.abstract.map((p) => bodyParagraph(p, { noIndent: true })),
    keywordParagraph(
      "realized variance, option-market information, intraday forecasting, QLIKE, temporal validation",
    ),
    heading1("1. Introduction"),
    heading2("1.1 Background and Context"),
    bodyParagraph(item3.introduction[0]),
    heading2("1.2 Problem Definition"),
    bodyParagraph(item3.introduction[1]),
    heading2("1.3 Purpose, Scope, and Structure"),
    bodyParagraph(item3.introduction[2]),
    heading1("2. Methodology"),
    heading2("2.1 Search Strategy"),
    bodyParagraph(item3.methodology[0]),
    heading2("2.2 Inclusion, Exclusion, and Screening"),
    bodyParagraph(item3.methodology[1]),
    heading2("2.3 Quality Assessment"),
    bodyParagraph(item3.methodology[2]),
    heading1("3. Thematic Synthesis of Literature"),
    heading2("3.1 Data Characteristics and Preprocessing"),
    ...item3.theme1.map((p) => bodyParagraph(p)),
    heading2("3.2 Algorithms and Modelling Approaches"),
    ...item3.theme2.map((p) => bodyParagraph(p)),
    heading2("3.3 System and Architecture Considerations"),
    ...item3.theme3.map((p) => bodyParagraph(p)),
    heading2("3.4 Evaluation Metrics and Experimental Design"),
    ...item3.theme4.map((p) => bodyParagraph(p)),
    heading1("4. Critical Analysis"),
    ...item3.critical.map((p) => bodyParagraph(p)),
    heading1("5. Research Gaps"),
    ...item3.gaps.map((p) => bodyParagraph(p)),
    heading1("6. Implications for the Capstone Project"),
    ...item3.implications.map((p) => bodyParagraph(p)),
    heading1("7. Conclusion"),
    ...item3.conclusion.map((p) => bodyParagraph(p)),
    pageBreak(),
    heading1("8. References", { before: 0 }),
    ...references.map(referenceParagraph),
    heading1("Appendix A: Plain-Language Glossary", { before: 0, pageBreakBefore: true }),
    bodyParagraph(
      "The definitions below explain the specialised terms used in the report. They are project definitions and do not change the formal contracts in the MDS650 repository.",
      { noIndent: true },
    ),
    glossaryTable(),
  ];
  return new Document({
    ...baseDocumentOptions("Assessment Item 3 Literature Review"),
    sections: [coverSection("Assessment Item 3 — Literature Review"), bodySection(body, { startPage: 1 })],
  });
}

function item2Document() {
  const firstBody = [
    heading1("1. Introduction", { before: 0 }),
    ...item2.introduction.map((p) => bodyParagraph(p)),
    heading1("2. Main Review"),
    heading2("2.1 Measuring the Target and Preparing High-Frequency Data"),
    ...item2.targetTheme.map((p) => bodyParagraph(p)),
    heading2("2.2 Option-Market Information: State Versus Trading Activity"),
    ...item2.optionTheme.map((p) => bodyParagraph(p)),
    heading2("2.3 Econometric, Machine-Learning, and Hybrid Models"),
    ...item2.modelTheme.map((p) => bodyParagraph(p)),
    heading2("2.4 Evaluation Design, Timing, and Reproducibility"),
    ...item2.evaluationTheme.map((p) => bodyParagraph(p)),
  ];

  const tableSection = [
    new Paragraph({
      spacing: { after: 40 },
      children: [
        new TextRun({ text: "Table 1", bold: true, font: "Times New Roman", size: 20 }),
      ],
    }),
    new Paragraph({
      spacing: { after: 100 },
      children: [
        new TextRun({
          text: "Comparison of the Ten Complete-Text Studies",
          italic: true,
          font: "Times New Roman",
          size: 20,
        }),
      ],
    }),
    comparisonTable(),
    new Paragraph({
      spacing: { before: 80, after: 0 },
      children: [
        new TextRun({ text: "Note. ", italic: true, font: "Times New Roman", size: 16 }),
        new TextRun({
          text: "Blue rows are the five core studies. Portfolio rank measures usefulness for this capstone, not universal study quality or citation impact. RV = realized variance; IV = implied volatility; QLIKE = quasi-likelihood loss.",
          font: "Times New Roman",
          size: 16,
        }),
      ],
    }),
  ];

  const finalBody = [
    heading1("3. Gaps in the Literature and Project Justification", { before: 0 }),
    ...item2.gaps.map((p) => bodyParagraph(p)),
    heading1("4. Conclusion"),
    ...item2.conclusion.map((p) => bodyParagraph(p)),
    pageBreak(),
    heading1("5. References", { before: 0 }),
    ...references.map(referenceParagraph),
    heading1("Appendix A: Plain-Language Glossary", { before: 0, pageBreakBefore: true }),
    bodyParagraph(
      "The definitions below explain the specialised terms used in the report. They are project definitions and do not change the formal contracts in the MDS650 repository.",
      { noIndent: true },
    ),
    glossaryTable(),
  ];

  return new Document({
    ...baseDocumentOptions("Assessment Item 2 Literature Review"),
    sections: [
      coverSection("Assessment Item 2 — Literature Review"),
      bodySection(firstBody, { startPage: 1 }),
      bodySection(tableSection, { orientation: PageOrientation.LANDSCAPE }),
      bodySection(finalBody),
    ],
  });
}

async function main() {
  const counts = auditContent();
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  const [item3Buffer, item2Buffer] = await Promise.all([
    Packer.toBuffer(item3Document()),
    Packer.toBuffer(item2Document()),
  ]);
  fs.writeFileSync(ITEM_3_PATH, item3Buffer);
  fs.writeFileSync(ITEM_2_PATH, item2Buffer);
  console.log(
    JSON.stringify(
      {
        outputs: [ITEM_3_PATH, ITEM_2_PATH],
        wordCounts: counts,
        bytes: {
          item3: item3Buffer.length,
          item2: item2Buffer.length,
        },
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
