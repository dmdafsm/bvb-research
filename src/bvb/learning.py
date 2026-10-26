"""Continutul paginii "Invatare": conceptele folosite in dashboard, cu metodologia
din cod, formule (LaTeX) si linkuri pentru detalii.

Textele descriu ce face codul din acest repo (analytics, adjust, valuation,
portfolio, risk); cand se schimba un calcul, se actualizeaza si aici.
"""

from dataclasses import dataclass

PAGES = ("Emitent", "Screener", "Portofoliu", "Calendar si anunturi")

TOPICS = (
    "Date si preturi",
    "Randament",
    "Risc",
    "Lichiditate",
    "Evaluare",
    "Backtest de portofoliu",
    "Risc de portofoliu",
    "Anunturi si calendar",
)


@dataclass(frozen=True)
class Concept:
    key: str
    title: str
    topic: str
    pages: tuple[str, ...]
    summary: str
    formulas: tuple[str, ...] = ()
    method: str = ""
    links: tuple[tuple[str, str], ...] = ()


def wiki(page: str) -> str:
    return f"https://en.wikipedia.org/wiki/{page}"


CONCEPTS: tuple[Concept, ...] = (
    # --- Date si preturi -------------------------------------------------------
    Concept(
        "sources",
        "Surse de date si actualizare",
        "Date si preturi",
        PAGES,
        "Toate cifrele vin din date publice, colectate local: preturile de inchidere si fisele emitentilor de pe "
        "bvb.ro, situatiile financiare anuale de pe data.gov.ro (Ministerul Finantelor, CC-BY 4.0), "
        "stiri din fluxurile RSS ZF si Profit.ro.",
        method="Preturile sunt de sfarsit de zi (deschidere, maxim, minim, inchidere, volum), nu in timp real. "
        "Colectarea ruleaza in zilele lucratoare la 19:15; datele unei zile sunt considerate finale dupa 18:30, "
        "cand sedinta si licitatia de inchidere s-au incheiat. Sambata se reiau istoricul complet si fisele "
        "emitentilor. Dashboard-ul citeste o copie "
        "a bazei publicata la finalul fiecarei colectari; ora apare in bara laterala.",
        links=(("Bursa de Valori Bucuresti", "https://bvb.ro"), ("data.gov.ro", "https://data.gov.ro")),
    ),
    Concept(
        "adjusted",
        "Pret ajustat pentru evenimente de capital",
        "Date si preturi",
        ("Emitent", "Screener", "Portofoliu"),
        "Actiunile gratuite, splitarile si consolidarile schimba pretul fara sa schimbe valoarea detinuta. "
        "Pretul ajustat imparte istoricul la factorul evenimentului, ca graficul si randamentele sa fie comparabile.",
        formulas=(
            r"\text{adj\_close}_t = \text{close}_t \cdot k_t,\qquad "
            r"k_t = \prod_{e:\ t < t_e} \frac{1}{r_e}",
        ),
        method="Factorii $r_e$ (cate actiuni noi la una veche) se iau din seria ajustata a graficului BVB: "
        "acolo unde raportul pret ajustat / pret brut sare de la o zi la alta peste 0,5% (plus o toleranta "
        "pentru rotunjirea BVB la 4 zecimale), BVB a aplicat un eveniment. Un salt care cade pe o data "
        "ex-dividend fara modificare de capital e tratat ca dividend, ca sa nu fie numarat de doua ori. "
        "Unde BVB n-a ajustat, evenimentul se deduce din modificarea numarului de actiuni, doar daca "
        "miscarea pretului il confirma (in limita a 25%, sau 50% dupa o suspendare de peste 20 de zile).",
        links=(("Stock split", wiki("Stock_split")),),
    ),
    Concept(
        "total_return",
        "Randament total (dividende reinvestite)",
        "Date si preturi",
        ("Emitent", "Screener", "Portofoliu"),
        "Seria de randament total presupune ca fiecare dividend brut e reinvestit in aceeasi actiune la data ex. "
        "Asa se compara corect o actiune cu dividende mari cu una fara dividende.",
        formulas=(
            r"\text{tr\_close}_t = \text{adj\_close}_t \cdot \prod_{d:\ t < t^{ex}_d} "
            r"\frac{P^{ex}_d}{P^{ex}_d + D_d}",
            r"1 + R_{t^{ex}} = \frac{P^{ex} + D}{P_{t^{ex}-1}}",
        ),
        method="$P^{ex}$ este prima inchidere incepand cu data ex, $D$ dividendul brut pe actiune (adus la "
        "numarul actual de actiuni). Forma $P^{ex}/(P^{ex}+D)$ ramane corecta si pentru dividende mari "
        "fata de pret. Pe pagina Emitent, 'Pret/an' foloseste pretul ajustat (fara dividende), iar "
        "'Randament total/an' seria cu dividende.",
        links=(("Total shareholder return", wiki("Total_shareholder_return")),),
    ),
    Concept(
        "ex_date",
        "Data ex-dividend si decontarea T+2",
        "Date si preturi",
        ("Emitent", "Calendar si anunturi"),
        "Cine cumpara cel tarziu in ziua dinaintea datei ex primeste dividendul; de la data ex pretul scade, "
        "in principiu, cu valoarea dividendului.",
        method="Cand BVB publica doar data de inregistrare, data ex se estimeaza: o zi de tranzactionare "
        "inainte de inregistrare de la 6 octombrie 2014 (decontare T+2), doua zile inainte de atunci (T+3). "
        "Alertele de ex-dividend apar cu 7 zile inainte.",
        links=(("Ex-dividend date", wiki("Ex-dividend_date")), ("T+2", wiki("T%2B2"))),
    ),
    Concept(
        "calendar",
        "Calendarul de tranzactionare si zilele fara tranzactii",
        "Date si preturi",
        ("Emitent", "Screener", "Portofoliu"),
        "Toate seriile se aliniaza pe zilele in care s-a calculat indicele BET. Intr-o zi fara tranzactii, "
        "pretul unei actiuni se reporteaza din ziua precedenta (randament 0).",
        method="Reportarea face seriile comparabile, dar pentru actiunile nelichide subestimeaza "
        "volatilitatea, beta si corelatiile (pretul pare stabil doar pentru ca nu se tranzactioneaza). De aceea "
        "lichiditatea apare mereu langa indicatorii de risc, iar corelatiile si beta din portofoliu se "
        "calculeaza pe randamente saptamanale.",
    ),
    Concept(
        "benchmark",
        "Indicele de referinta: BET-TR",
        "Date si preturi",
        ("Emitent", "Screener", "Portofoliu"),
        "BET-TR este indicele BET (cele mai lichide companii de pe BVB) in varianta total return: include "
        "dividendele reinvestite, deci se compara corect cu randamentul total al actiunilor.",
        formulas=(r"B_t = \text{BET}_t \cdot \frac{\text{BET-TR}_{t_0}}{\text{BET}_{t_0}},\quad t < t_0",),
        method="BET-TR exista din 19 septembrie 2014. Inainte, seria se prelungeste cu BET (fara dividende), "
        "scalat la nivelul BET-TR din prima zi ($t_0$); pentru perioadele vechi comparatia favorizeaza "
        "usor actiunile.",
        links=(("Bucharest Stock Exchange", wiki("Bucharest_Stock_Exchange")),),
    ),
    # --- Randament -------------------------------------------------------------
    Concept(
        "cagr",
        "CAGR (randament anual compus)",
        "Randament",
        ("Emitent", "Screener", "Portofoliu"),
        "Rata anuala constanta care ar duce de la valoarea initiala la cea finala in acelasi timp.",
        formulas=(r"\text{CAGR} = \left(\frac{V_T}{V_0}\right)^{1/n} - 1,\qquad n = \frac{\text{zile}}{365{,}25}",),
        method="Se calculeaza pe randamentul total (sau pe NAV in backtest). Ferestrele de pe pagina Emitent "
        "(1, 3, 5, 10 ani) apar doar daca seria acopera fereastra, cu cel mult 31 de zile lipsa la inceput.",
        links=(("Compound annual growth rate", wiki("Compound_annual_growth_rate")),),
    ),
    Concept(
        "yearly",
        "Randament pe ani calendaristici",
        "Randament",
        ("Portofoliu",),
        "Cresterea valorii de la ultima zi a anului precedent la ultima zi a anului.",
        formulas=(r"R_{an} = \frac{V_{\text{sfarsit an}}}{V_{\text{sfarsit an precedent}}} - 1",),
        method="Primul an incepe de la data de start a backtestului, iar ultimul se opreste la ultima zi "
        "cu date, deci pot fi partiali.",
    ),
    # --- Risc ------------------------------------------------------------------
    Concept(
        "volatility",
        "Volatilitate",
        "Risc",
        ("Emitent", "Screener", "Portofoliu"),
        "Cat de mult variaza randamentele zilnice in jurul mediei, anualizat. Doua actiuni cu acelasi "
        "randament mediu pot avea drumuri foarte diferite.",
        formulas=(r"r_t = \frac{V_t}{V_{t-1}} - 1,\qquad \sigma_{an} = \operatorname{std}(r_t)\cdot\sqrt{252}",),
        method="252 de zile de tranzactionare pe an. Zilele fara tranzactii au randament 0 (vezi calendarul), "
        "ceea ce scade volatilitatea actiunilor nelichide.",
        links=(("Volatility (finance)", wiki("Volatility_(finance)")),),
    ),
    Concept(
        "sharpe",
        "Raportul Sharpe",
        "Risc",
        ("Emitent", "Screener", "Portofoliu"),
        "Randament pe unitate de risc: cat randament mediu aduce fiecare unitate de volatilitate.",
        formulas=(r"S = \frac{\bar r - r_f/252}{\operatorname{std}(r_t)}\cdot\sqrt{252}",),
        method="Rata fara risc $r_f$ este 0 in dashboard, deci valoarea e usor optimista fata de definitia "
        "clasica (dobanda la titlurile de stat a fost semnificativa in multe perioade). Peste 1 e in general "
        "bun, peste 2 foarte bun; comparati intre actiuni pe aceeasi fereastra.",
        links=(("Sharpe ratio", wiki("Sharpe_ratio")),),
    ),
    Concept(
        "drawdown",
        "Max drawdown",
        "Risc",
        ("Emitent", "Screener", "Portofoliu"),
        "Cea mai mare scadere procentuala de la un varf la minimul urmator: cat ai fi pierdut daca ai fi "
        "cumparat in cel mai prost moment si ai fi vandut in cel mai prost moment.",
        formulas=(r"\text{MDD} = \min_t \left(\frac{V_t}{\max_{s \le t} V_s} - 1\right)",),
        method="Pe randamentul total. In backtest se compara cu drawdown-ul BET-TR pe aceeasi perioada.",
        links=(("Drawdown (economics)", wiki("Drawdown_(economics)")),),
    ),
    Concept(
        "beta",
        "Beta",
        "Risc",
        ("Emitent", "Screener", "Portofoliu"),
        "Sensibilitatea fata de piata: beta 1,2 inseamna ca, in medie, actiunea a crescut sau a scazut cu "
        "1,2% cand BET-TR s-a miscat cu 1%.",
        formulas=(r"\beta = \frac{\operatorname{cov}(r_i, r_m)}{\operatorname{var}(r_m)}",),
        method="$r_m$ este randamentul BET-TR. Pe Emitent si Screener beta se calculeaza pe randamente "
        "zilnice; in Portofoliu pe randamente saptamanale (vineri la vineri), mai robuste pentru actiunile "
        "care nu se tranzactioneaza zilnic.",
        links=(("Beta (finance)", wiki("Beta_(finance)")),),
    ),
    # --- Lichiditate -------------------------------------------------------------
    Concept(
        "liquidity",
        "Zile tranzactionate si rulaj mediu",
        "Lichiditate",
        ("Emitent", "Screener", "Portofoliu"),
        "Cat de usor se poate cumpara sau vinde o actiune fara sa misti pretul. Pe BVB multe actiuni nu "
        "se tranzactioneaza zilnic.",
        formulas=(
            r"\%\,\text{zile} = \frac{\#\{t: \text{volum}_t > 0\}}{\#\text{sedinte}}",
            r"\text{Rulaj/zi} = \frac{\sum_t \text{valoare}_t}{\#\text{sedinte}}",
        ),
        method="Pe ultimul an (Emitent, Screener) sau pe ultimele 6 luni (riscul de lichiditate din "
        "Portofoliu). Rulajul mediu imparte la toate sedintele, inclusiv cele fara tranzactii. Screener-ul "
        "exclude implicit actiunile tranzactionate in mai putin de 80% din sedinte.",
        links=(("Market liquidity", wiki("Market_liquidity")),),
    ),
    # --- Evaluare --------------------------------------------------------------
    Concept(
        "market_cap",
        "Capitalizare bursiera",
        "Evaluare",
        ("Emitent", "Screener"),
        "Valoarea de piata a tuturor actiunilor companiei.",
        formulas=(
            r"\text{Cap} = P \cdot N",
            r"\text{Cap}_t = P_t \cdot N_{azi} \cdot k_t\ \ \text{(istoric)}",
        ),
        method="$N$ este numarul actual de actiuni din fisa emitentului. Pentru capitalizarea istorica "
        "(multiplii in timp), numarul actual se aduce inapoi cu factorul de capital $k_t$; emisiunile cu "
        "bani si rascumpararile nu sunt prinse.",
        links=(("Market capitalization", wiki("Market_capitalization")),),
    ),
    Concept(
        "dividend_yield",
        "Randament din dividende (12 luni)",
        "Evaluare",
        ("Emitent", "Screener"),
        "Dividendele brute cu data ex in ultimele 12 luni, raportate la pretul curent.",
        formulas=(r"DY = \frac{\sum_{t^{ex} \in (t-1\,an,\ t]} D \cdot k_{t^{ex}} / k_t}{P_t}",),
        method="Dividendele platite inainte de actiuni gratuite sau consolidari sunt aduse la numarul actual "
        "de actiuni prin factorul de capital. Este un randament trecut, nu o estimare a urmatorului dividend.",
        links=(("Dividend yield", wiki("Dividend_yield")),),
    ),
    Concept(
        "pe_pb",
        "P/E si P/B",
        "Evaluare",
        ("Emitent", "Screener"),
        "Cat plateste piata pentru un leu de profit (P/E) sau pentru un leu de capitaluri proprii (P/B).",
        formulas=(
            r"P/E = \frac{\text{Cap}}{\text{Profit net}},\qquad P/B = \frac{\text{Cap}}{\text{Capitaluri proprii}}",
        ),
        method="Din situatiile financiare anuale INDIVIDUALE de pe data.gov.ro, nu cele consolidate: pentru "
        "holdinguri (de ex. EL, M) sau grupuri cu filiale mari, multiplii difera de cei raportati pe grup. "
        "Se calculeaza doar pentru profit si capitaluri pozitive. Exercitiul N se considera disponibil din "
        "1 iunie N+1 (termenul de depunere), ca evaluarile istorice sa nu foloseasca date din viitor.",
        links=(
            ("Price-earnings ratio", wiki("Price%E2%80%93earnings_ratio")),
            ("P/B ratio", wiki("P/B_ratio")),
            ("Consolidated financial statement", wiki("Consolidated_financial_statement")),
        ),
    ),
    Concept(
        "pe_percentile",
        "P/E fata de propriul istoric (percentila 10 ani)",
        "Evaluare",
        ("Emitent", "Screener"),
        "Unde se afla P/E-ul de azi fata de valorile lunare din ultimii 10 ani: 0% inseamna cel mai ieftin, "
        "100% cel mai scump din istoric.",
        formulas=(r"\text{pct} = \frac{\#\{m: P/E_m < P/E_{azi}\}}{\#\{m\}}",),
        method="Pe valori lunare, fiecare luna cu exercitiul disponibil atunci (regula de 1 iunie). Apare "
        "doar daca exista cel putin 24 de luni cu P/E pozitiv.",
        links=(("Percentile rank", wiki("Percentile_rank")),),
    ),
    Concept(
        "quality",
        "ROE, marja neta, datorii/capitaluri",
        "Evaluare",
        ("Emitent", "Screener"),
        "Indicatori de calitate din situatiile financiare anuale.",
        formulas=(
            r"ROE_N = \frac{\text{Profit net}_N}{(\text{Cap. proprii}_N + \text{Cap. proprii}_{N-1})/2}",
            r"\text{Marja neta} = \frac{\text{Profit net}}{\text{Cifra de afaceri}},\qquad "
            r"D/E = \frac{\text{Datorii totale}}{\text{Capitaluri proprii}}",
        ),
        method="ROE foloseste media capitalurilor proprii pe doi ani. Payout-ul (Emitent) este totalul "
        "dividendelor distribuite din profitul exercitiului impartit la profitul net. La banci cifra de "
        "afaceri lipseste (structura situatiilor e diferita), deci marja nu se calculeaza.",
        links=(
            ("Return on equity", wiki("Return_on_equity")),
            ("Profit margin", wiki("Profit_margin")),
            ("Debt-to-equity ratio", wiki("Debt-to-equity_ratio")),
        ),
    ),
    # --- Backtest ----------------------------------------------------------------
    Concept(
        "backtest",
        "Cum functioneaza backtestul",
        "Backtest de portofoliu",
        ("Portofoliu",),
        "O simulare: ce s-ar fi intamplat daca ai fi investit suma aleasa in ponderile date, la data de start.",
        method="Tranzactiile se fac la pretul de inchidere, in actiuni ajustate (actiunile gratuite si "
        "consolidarile sunt deja incluse). Daca o actiune nu era listata la start, startul se muta la prima "
        "zi cu preturi pentru toate. Un ordin nu e niciodata blocat de lipsa tranzactiilor (pretul se "
        "reporteaza), deci pentru actiuni nelichide rezultatul e optimist. Rezultatele trecute nu garanteaza "
        "rezultate viitoare.",
        links=(("Backtesting", wiki("Backtesting")),),
    ),
    Concept(
        "rebalancing",
        "Rebalansare",
        "Backtest de portofoliu",
        ("Portofoliu",),
        "Readucerea pozitiilor la ponderile tinta: vinzi ce a crescut peste pondere si cumperi ce a ramas sub.",
        formulas=(r"q_i = \frac{w_i \cdot (NAV - \text{comision estimat})}{P_i}",),
        method="In prima zi de tranzactionare a lunii, trimestrului sau anului. 'Fara' lasa ponderile sa "
        "evolueze liber. O actiune delistata se vinde la ultimul pret dupa ultima zi cu tranzactii; la "
        "urmatoarea rebalansare ponderea ei se imparte celorlalte (fara rebalansare, banii raman cash).",
        links=(("Rebalancing investments", wiki("Rebalancing_investments")),),
    ),
    Concept(
        "dividends_tax_fees",
        "Dividende, impozit si comisioane in backtest",
        "Backtest de portofoliu",
        ("Portofoliu",),
        "Dividendele se incaseaza la data ex, net de impozitul pe dividende de la acea data, si se "
        "reinvestesc in aceeasi actiune sau raman numerar.",
        formulas=(
            r"\text{Dividend net} = q \cdot D \cdot (1 - \tau_{an}),\qquad \text{Comision} = f \cdot |\text{valoare}|",
        ),
        method="Cota $\\tau$ pentru persoane fizice rezidente: 16% pana in 2015, 5% in 2016-2022, 8% in "
        "2023-2024, 10% in 2025 si 16% din 2026. Comisionul $f$ se aplica la fiecare cumparare si vanzare, "
        "inclusiv la reinvestirea dividendelor. BET-TR, folosit pentru comparatie, reinvesteste dividendele "
        "brute si nu are comisioane, deci il avantajeaza usor.",
        links=(("Dividend reinvestment plan", wiki("Dividend_reinvestment_plan")),),
    ),
    Concept(
        "survivorship",
        "Actiuni delistate si biasul supravietuitorului",
        "Backtest de portofoliu",
        ("Emitent", "Portofoliu"),
        "Un test care foloseste doar companiile listate azi ignora companiile care au disparut si arata mai "
        "bine decat realitatea.",
        method="Baza contine si ~4.600 de actiuni delistate cu istoric pe BVB (majoritatea foste RASDAQ). "
        "In backtest, dupa ultima tranzactie pozitia se vinde la ultimul pret; pretul real de iesire (oferta "
        "de preluare, faliment) poate fi diferit.",
        links=(("Survivorship bias", wiki("Survivorship_bias")),),
    ),
    # --- Risc de portofoliu ----------------------------------------------------
    Concept(
        "var",
        "VaR si CVaR",
        "Risc de portofoliu",
        ("Portofoliu",),
        "VaR 95%: pierderea zilnica depasita doar in 5% din zile. CVaR (expected shortfall): pierderea medie "
        "in acele 5% zile rele, adica cat de rau e cand e rau.",
        formulas=(
            r"\text{VaR}^{ist}_c = -q_{1-c}(r_p),\qquad \text{CVaR}^{ist}_c = -\mathbb{E}[r_p \mid r_p \le q_{1-c}]",
            r"\text{VaR}^{par}_c = z_c\,\sigma_p,\qquad \text{CVaR}^{par}_c = \sigma_p\,\frac{\varphi(z_c)}{1-c}",
        ),
        method="Ponderile de azi aplicate pe randamentele zilnice din ultimii 3 ani (doar zilele cu date pentru "
        "toate pozitiile). Varianta istorica foloseste distributia reala; cea parametrica presupune "
        "distributie normala cu $\\sigma_p$ din covarianta Ledoit-Wolf, $z_c$ si $\\varphi$ fiind cuantila si "
        "densitatea normalei standard. Pierderile mari sunt de obicei mai frecvente decat prezice normala, deci "
        "varianta istorica e de regula mai prudenta in coada.",
        links=(
            ("Value at risk", wiki("Value_at_risk")),
            ("Expected shortfall", wiki("Expected_shortfall")),
            ("Normal distribution", wiki("Normal_distribution")),
        ),
    ),
    Concept(
        "covariance",
        "Covarianta cu shrinkage Ledoit-Wolf",
        "Risc de portofoliu",
        ("Portofoliu",),
        "Covarianta estimata direct din cateva sute de zile e zgomotoasa, mai ales cu multe actiuni. "
        "Shrinkage-ul o trage spre o matrice simpla, reducand erorile de estimare.",
        formulas=(
            r"\hat\Sigma = \delta\,\mu I + (1-\delta)\,S,\qquad \mu = \frac{\operatorname{tr}(S)}{p}",
            r"\sigma_p = \sqrt{w^\top \hat\Sigma\, w}",
        ),
        method="$S$ este covarianta esantionului, $p$ numarul de actiuni, iar intensitatea $\\delta$ se alege "
        "automat (formula Ledoit-Wolf) dupa cat de zgomotoase sunt datele.",
        links=(
            ("Estimation of covariance matrices", wiki("Estimation_of_covariance_matrices")),
            ("scikit-learn: shrunk covariance", "https://scikit-learn.org/stable/modules/covariance.html"),
        ),
    ),
    Concept(
        "risk_contribution",
        "Contributia la risc",
        "Risc de portofoliu",
        ("Portofoliu",),
        "Ce parte din volatilitatea portofoliului vine din fiecare pozitie. O pozitie cu pondere mica dar "
        "foarte volatila poate domina riscul.",
        formulas=(r"RC_i = \frac{w_i\,(\hat\Sigma w)_i}{w^\top \hat\Sigma\, w},\qquad \sum_i RC_i = 1",),
        links=(("Risk parity", wiki("Risk_parity")),),
    ),
    Concept(
        "correlation",
        "Corelatii",
        "Risc de portofoliu",
        ("Portofoliu",),
        "Cat de mult se misca doua actiuni impreuna: 1 identic, 0 independent, -1 opus. Corelatiile mici "
        "intre pozitii reduc riscul total (diversificare).",
        formulas=(r"\rho_{ij} = \frac{\operatorname{cov}(r_i, r_j)}{\sigma_i\,\sigma_j}",),
        method="Pe randamente saptamanale din ultimii 3 ani, ca zilele fara tranzactii sa nu scada artificial "
        "corelatiile.",
        links=(("Pearson correlation coefficient", wiki("Pearson_correlation_coefficient")),),
    ),
    Concept(
        "stress",
        "Scenarii de stres",
        "Risc de portofoliu",
        ("Portofoliu",),
        "Cum s-ar fi comportat portofoliul de azi in crize trecute si la scaderi ipotetice ale pietei.",
        formulas=(
            r"R^{scen}_p = \sum_i w_i R_i,\qquad R_i \approx \beta_i\,R_{BET\text{-}TR}\ \text{daca nu era listata}",
        ),
        method="Episoade istorice (aproximativ de la varful la minimul BET): criza financiara 2007-2009, criza "
        "datoriilor din zona euro 2011, OUG 114/2018, COVID-19 2020, invazia Ucrainei 2022. Socuri ipotetice "
        "de -10%, -20%, -30% pe BET-TR, transmise prin beta saptamanal.",
        links=(("Stress test (financial)", wiki("Stress_test_(financial)")),),
    ),
    Concept(
        "concentration",
        "Concentrare: HHI si pozitii efective",
        "Risc de portofoliu",
        ("Portofoliu",),
        "Cat de dependent e portofoliul de cateva pozitii, sectoare sau de stat.",
        formulas=(r"HHI = \sum_i w_i^2,\qquad N_{ef} = \frac{1}{HHI}",),
        method="$N_{ef}$ = numarul de pozitii egale cu aceeasi concentrare (5 pozitii de 20% dau 5; 50/30/20 "
        "dau 2,6). 'Control de stat' = ponderea companiilor in care statul detine cel putin 50%: suma "
        "actionarilor de tip Statul Roman, ministere, Secretariatul General al Guvernului sau autoritati "
        "locale, din structura actionariatului de pe fisa emitentului.",
        links=(("Herfindahl-Hirschman index", wiki("Herfindahl%E2%80%93Hirschman_index")),),
    ),
    Concept(
        "liquidity_risk",
        "Riscul de lichiditate: zile pentru vanzare",
        "Risc de portofoliu",
        ("Portofoliu",),
        "In cate sedinte poti vinde o pozitie fara sa depasesti o parte rezonabila din rulajul zilnic.",
        formulas=(
            r"\text{Zile}_i = \frac{w_i \cdot V}{0{,}2 \cdot ADV_i}",
            r"\text{Vandabil in } h \text{ zile} = \sum_i w_i \min\!\left(1, \frac{h}{\text{Zile}_i}\right)",
        ),
        method="$ADV$ = rulajul mediu zilnic din ultimele 6 luni, $V$ = valoarea portofoliului; participarea "
        "de 20% din volum este o regula prudenta folosita frecvent. O actiune fara rulaj nu poate fi vanduta "
        "in acest model.",
        links=(("Liquidity risk", wiki("Liquidity_risk")),),
    ),
    # --- Anunturi si calendar --------------------------------------------------
    Concept(
        "reports",
        "Rapoarte curente si categoriile lor",
        "Anunturi si calendar",
        ("Emitent", "Calendar si anunturi"),
        "Emitentii publica pe BVB rapoarte curente despre evenimentele care pot influenta pretul: rezultate, "
        "AGA, dividende, tranzactii ale conducerii, contracte, litigii.",
        method="Categoria se deduce din titlu, prin cuvinte cheie: insider (tranzactii ale conducerii, art. 19 "
        "MAR), buyback, dividend, results, agm, calendar, holdings (praguri de detinere), related_party, "
        "management, contract, rating, nav, legal, shareholders, trading, capital; restul 'other'. Acelasi "
        "raport gasit pe pagina globala BVB si pe fisa emitentului e pastrat o singura data.",
        links=(
            ("Regulamentul (UE) 596/2014 (MAR)", "https://eur-lex.europa.eu/eli/reg/2014/596/oj"),
            ("Insider trading", wiki("Insider_trading")),
        ),
    ),
    Concept(
        "financial_calendar",
        "Calendar financiar si AGA",
        "Anunturi si calendar",
        ("Emitent", "Calendar si anunturi"),
        "Datele anuntate de emitenti pentru rezultate, adunari generale (AGA) si dividende.",
        method="Din calendarul financiar si sectiunea AGA a fisei emitentului, plus datele ex-dividend. "
        "Datele pot fi modificate ulterior de emitent; sursa de referinta ramane raportul curent.",
        links=(("Annual general meeting", wiki("Annual_general_meeting")),),
    ),
    Concept(
        "news",
        "Stiri asociate emitentilor",
        "Anunturi si calendar",
        ("Emitent", "Calendar si anunturi"),
        "Titluri din fluxurile RSS ZF si Profit.ro, legate de emitenti dupa nume si aliasuri.",
        method="Potrivirea cauta in titlu si rezumat simbolul, numele companiei si aliasuri cunoscute (de ex. "
        "Banca Transilvania pentru TLV). Se pastreaza doar titlul, linkul, un rezumat scurt si data; articolul "
        "se citeste pe site-ul sursei. Pot aparea potriviri gresite pentru nume foarte comune.",
    ),
)


def by_topic(concepts=CONCEPTS) -> dict[str, list[Concept]]:
    out: dict[str, list[Concept]] = {t: [] for t in TOPICS}
    for c in concepts:
        out[c.topic].append(c)
    return {t: cs for t, cs in out.items() if cs}


def search(query: str, pages: list[str] | None = None, concepts=CONCEPTS) -> list[Concept]:
    q = query.strip().lower()
    out = []
    for c in concepts:
        if pages and not set(pages) & set(c.pages):
            continue
        if q and q not in " ".join((c.title, c.summary, c.method, c.topic)).lower():
            continue
        out.append(c)
    return out
