# eVestment Reference Guide

> **Auto-Extracted from PDF via Netz Analysis Engine**

---

### Page 1

EVESTMENT 
Investment Statistics Guide 
Gain a better understanding of how to derive meaningful 
conclusions from investment statistics 

---

### Page 3

  
                                                                                      www.evestment.com | 1 
 
Table of Contents 
Table of Contents ...................................................................................................................... 1 
Introduction .............................................................................................................................. 4 
I. Using Statistics to Understand Return Characteristics ......................................................... 5 
Using Standard Deviation to Predict Possible Return Ranges .............................................. 6 
Assessing Skewness and Kurtosis in the Return Distribution ............................................... 8 
Predicting Returns using Monte Carlo Simulation............................................................... 10 
II. Risk Statistics and Risk-adjusted Statistics ....................................................................... 12 
Standard Deviation .............................................................................................................. 12 
Sharpe Ratio ........................................................................................................................ 14 
Sortino Ratio ........................................................................................................................ 15 
Omega Ratio ........................................................................................................................ 16 
Drawdown Analysis ............................................................................................................. 21 
Calmar Ratio ........................................................................................................................ 23 
Sterling Ratio ....................................................................................................................... 23 
Comparing Risk Statistics and Risk-adjusted Statistics ...................................................... 23 
III. Correlation and Regression Analysis ................................................................................ 24 
The Correlation Coefficient (R)............................................................................................ 24 
Alpha and Beta..................................................................................................................... 23 
The Coefficient of Determination (R2) ................................................................................. 23 
Benchmark Ratios ................................................................................................................ 24 
IV. Peer Group Analysis........................................................................................................... 26 
Top Quartile Performance ................................................................................................... 26 
Bottom Quartile Performance .............................................................................................. 27 
Manager Search Criteria ...................................................................................................... 27 
V. Composite Returns: Portfolio Construction, Optimization, Simulation .............................. 31 
Portfolio Construction ......................................................................................................... 31 
Optimization ........................................................................................................................ 36 
Simulation ............................................................................................................................ 38 
VI. Fat Tail Analysis, Risk Budgeting, Factor Analysis & Stress Testing ................................. 40 
Fat Tail Analysis ................................................................................................................... 40 
VaR (Value at Risk) .......................................................................................................... 40 
The Differences between Normal VaR, Modified VaR and “Fat-Tailed” VaR ................... 40 
− ETL (Expected Tail Loss) ........................................................................................... 41 
− ETR (Expected Tail Return) ....................................................................................... 41 
− STARR Performance .................................................................................................. 41 
− Rachev Ratio ............................................................................................................. 41 
− Marginal Contribution to Risk (MCTR) / Marginal Contribution to Expected Tail Loss 
(MCETL) ............................................................................................................................ 41 
− Percentage Contribution to Risk (PCTR) / Percentage Contribution to Expected Tail 

---

### Page 4

  
                                                                                      www.evestment.com | 2 
 
Loss (PCETL) .................................................................................................................... 41 
− Skew .......................................................................................................................... 41 
− Excess Kurtosis ......................................................................................................... 41 
− Implied Return .......................................................................................................... 42 
Risk Budgeting..................................................................................................................... 43 
Factor Analysis & Factor Contribution to Risk ..................................................................... 45 
Stress Testing ...................................................................................................................... 47 
VII. Measuring Private Equity Performance ........................................................................... 48 
Using IRRs as a Key Measure of Performance .................................................................... 48 
Predicting Repeatability of Success .................................................................................... 49 
Comparing Private Equity Returns to Public Markets ......................................................... 51 
Conclusion ............................................................................................................................... 53 
Appendix I: Key Investment Statistics ................................................................................... 54 
I. Absolute Return Measures ............................................................................................... 55 
1. Monthly Return (Arithmetic Mean): ............................................................................. 55 
2. Average Monthly Gain (Gain Mean): ............................................................................ 55 
3.  Average Monthly Loss (Loss Mean): ........................................................................... 55 
4.  Compound Monthly Return (Geometric):.................................................................... 56 
II. Absolute Risk-adjusted Return Measures ...................................................................... 57 
1.  Sharpe Ratio: ............................................................................................................... 57 
2.  Calmar Ratio: A return/risk ratio. ............................................................................... 57 
3.  Sterling Ratio: ............................................................................................................. 58 
4.  Sortino Ratio: .............................................................................................................. 58 
5.  Omega: ........................................................................................................................ 58 
III. Absolute Risk Measures ................................................................................................ 59 
1.  Monthly Standard Deviation: ...................................................................................... 59 
2.  Gain Standard Deviation: ............................................................................................ 59 
3.  Loss Standard Deviation: ............................................................................................ 60 
4.  Downside Deviation: ................................................................................................... 60 
5.  Semi Deviation: ........................................................................................................... 61 
6.  Skewness: ................................................................................................................... 61 
7.  Kurtosis: ...................................................................................................................... 62 
8.  Maximum Drawdown: ................................................................................................. 63 
9.  Gain/Loss Ratio: .......................................................................................................... 63 
IV. Relative Return Measures .............................................................................................. 64 
1.  Up Capture Ratio: ........................................................................................................ 64 
2.  Down Capture Ratio: ................................................................................................... 64 
3.  Up Number Ratio: ........................................................................................................ 65 
4.  Down Number Ratio: ................................................................................................... 66 
5.  Up Percentage Ratio (Proficiency Ratio): ................................................................... 66 
6.  Down Percentage Ratio (Proficiency Ratio): .............................................................. 67 
V.  Relative Risk-adjusted Return Measures ....................................................................... 68 
1.  Annualized Alpha: ....................................................................................................... 68 
2.  Treynor Ratio: ............................................................................................................. 68 

---

### Page 5

  
                                                                                      www.evestment.com | 3 
 
3.  Jensen Alpha: .............................................................................................................. 69 
4.  Information Ratio: ...................................................................................................... 69 
VI. Relative Risk Measure .................................................................................................... 70 
1.  Beta: ............................................................................................................................ 70 
VII. Tail Risk Measures ........................................................................................................ 71 
1.  Value at Risk (Parametric VaR): ................................................................................. 71 
2.  Modified Value at Risk: ............................................................................................... 71 
3.  Expected Tail Loss (ETL): ............................................................................................ 71 
4.  Modified Expected Tail Loss (ETL): ............................................................................. 71 
5.  Jarque-Bera: ................................................................................................................ 72 
6.  STARR (Stable Tail Adjusted Return Ratio): ............................................................... 72 
7.  Rachev Ratio: .............................................................................................................. 72 
VIII. Holdings Analysis Measures ........................................................................................ 73 
1. Active Share .............................................................................................................. 73 
2. Overlap: ..................................................................................................................... 73 
3. Peer Share ................................................................................................................. 73 
4. Active Share Efficiency .............................................................................................. 74 
5. Peer Share Efficiency ................................................................................................ 74 
IX.  Private Equity Performance Calculations ...................................................................... 75 
1. Internal Rate of Return ............................................................................................. 75 
2. Money Multiples ........................................................................................................ 75 
3. Additional Private Equity Metrics .............................................................................. 76 
 
 
 
 
 
 
 
 
 
 
 
 
 

---

### Page 6

  
                                                                                      www.evestment.com | 4 
 
 
 
 
 
 
 
 
Introduction 
The purpose of this Guide is to assist you in gaining a better understanding of how to derive meaningful 
conclusions from investment statistics. This guide is compiled from calculations from the various 
eVestment products including Analytics, PerTrac, Holdings Analysis, TopQ and Risk Plus. 
A glossary of the key investment terms used in this Guide is provided in Appendix I at the end of the 
document. 
Guide’s Learning Objectives 
The Guide’s learning objectives are as follows: 
1. Explain how to use statistics to predict future investment returns. 
2. Interpret the different investment risk statistics and risk-adjusted statistics. 
3. Explain the concepts of correlation and regression analysis for investment analysis. 
4. Describe the key characteristics of peer group analysis and its usefulness in the search process.  

---

### Page 7

  
                                                                                      www.evestment.com | 5 
 
I. Using Statistics to Understand Return Characteristics 
Investment statistics can be used in two ways: 
• To compare the performance  histories  of multiple investment managers 
• To try to predict a range of future returns for an investment. 
A.  Comparing Managers’ Track Records and Time Periods 
When using statistics to predict an investment’s return, it is critical to note that the length of the 
investment’s track record and the time frame will dramatically affect the calculations. For example, the 
average annual return of the S&P 500 Index, over the 36 ½ -year period from January 1975 to June 
2011, was 11.84%. However, as Figure 1 highlights, if we assess the same data using only 1- or 3-year 
rolling returns, they range between 61% and -43% on a 1-year rolling basis, and between 33% and -
16% on a 3-year rolling basis. 
 
Figure 1: Rolllng Returns - Take 1 
Rolling Armrn1tlzed Return for the S&P 500 lnclex 
!IO.OO'i6 ~-----------------------------------------
·60.00% ~----------------------------------------
Jari•75 Jan-80 Jan, 85 Jan•90 Jari•95 Jari•OO Jan-OS Jan•10 
- 1Year - 3Year - 3 Year M in -16.09 9' - 3 Year Ma~ 33.309' 

---

### Page 8

  
                                                                                      www.evestment.com | 6 
 
Similarly, if we assess a 5-year rolling period, the returns range between -3% and 20%. As Figure 2 
illustrates, only when we lengthen the period to 10 years do we begin to see a true reversion to the 
mean, or a narrowing of the spread of actual returns close to the long-term average or mean return. This 
means that if an investment has a 20% return one year, per- haps the best prediction for its return the 
next year is “I don’t know.”  A one-year time period doesn’t provide sufficient information from which to 
draw conclusions. Therefore, investors should not rely exclusively on statistics that only cover 1 -, 3- or 
even 5-year periods, since they may not be significant or meaningful over the long term. 
 
 
B. Understanding Investment Return Characteristics 
In this section, we review some of the methods and statistics used to predict investment returns, 
including standard deviation, skewness and kurtosis, and Monte Carlo simulation. 
Using Standard Deviation to Predict Possible Return Ranges 
Can we use historical returns to predict future investment returns? As you can see with Figure 2, despite 
all of our carefully analyzed averages of historical returns, the S&P 500 Index still experienced one of its 
worst returns ever in 2008. 
 
To help us predict future returns, we can generate a range of probabilities for the expected returns using 
standard deviation as a mathematical measure of predictability, rather than using historical averages. 
20.00% 
-60_00'11, 
Jari-75 
- lYear 
Jan-80 
- 3Year 
Figure 2: Rolling Returns - Take 2 
Rolling Annualized Return for the S&P 500 Index 
Jan-85 Jan-90 Jan-95 Jari-00 
- svear - 10 Year Min -3.43% - lOYear Max 19.49% 
Jan-OS Jan-10 
- llDYear) 

---

### Page 9

  
                                                                                      www.evestment.com | 7 
 
Standard deviation enables us to generate a probable range of expected returns. To demonstrate this, we 
can assess the returns of the S&P 500 Index and develop a normal, bell-shaped distribution of returns for 
the Index. Figure 3 illustrates the distribution of monthly returns for the S&P 500 Index. 
 
From Figure 3, we see that the mean monthly return for the S&P 500 Index is 1.04% for the period 
January 1975 to June 2011. If we try to predict next month’s return, based on this information alone, 
there is a 50% chance that the return will exceed 1.04%, and a 50% chance it will not achieve this 
return. As Figure 4 illustrates, there is a 75% chance that the next monthly return will be greater than -
1.66%, according to the shaded area under the curve. While some might find this information beneficial, 
there are significant problems with relying too heavily upon standard deviation as a predictive statistic. 
Perhaps the biggest problem is that very few investments display a normal distribution. 
16 
Figure 3: Distribution of Monthly Returns for the S&P 500 
Figure 4: Returns and Standard Deviation - Take II 
Distribution of Monthly Returns for the S&P 500 Index 
14 +-------------------- -----
Mean= 1.27% 
Standard Deviation = 4.38% 
12 
10 
8 
75% confidence return will be greater 
than -1.66% 
Area under 
curve is 75% 

---

### Page 10

  
                                                                                      www.evestment.com | 8 
 
Assessing Skewness and Kurtosis in the Return Distribution 
When returns fall outside of a normal distribution, the distribution exhibits skewness or kurtosis. 
Skewness is known as the third “moment” of a return distribution and kurtosis is known as the fourth 
moment of the return distribution, with the mean and the variance being the first and second moments, 
respectively. (Variance is a statistic that is closely related to standard deviation; both measure the 
dispersion of an investment’s historical returns.) Ideally, investors should consider all four moments or 
characteristics of an investment’s return distribution. 
• Skewness: Skewness measures the degree of asymmetry of a distribution around its mean. 
Positive skewness indicates a distribution with an asymmetric tail extending toward more positive 
values. Negative skewness indicates a distribution with an asymmetric tail extending toward more 
negative values. 
• Kurtosis: Kurtosis measures the degree to which a distribution is more or less peaked than a 
normal distribution. Positive kurtosis indicates a relatively peaked distribution. Negative kurtosis 
indicates a relatively flat distribution. A normal distribution has a kurtosis of 3. Therefore, an 
investment characterized by high kurtosis will have “fat tails” (higher frequencies of outcomes) at 
the extreme negative and positive ends of the distribution curve. A distribution of returns 
exhibiting high kurtosis tends to overestimate the probability of achieving the mean return. 
Figure 5 illustrates both the skewness and kurtosis in the return distribution for the S&P 500 Index from 
Figure 4. The skewness is negative, which tells us that the returns are negatively biased. Because 
kurtosis measures the steepness of the curve, we can tell that there is a steep curve by reviewing the 
kurtosis number. A kurtosis less than zero indicate a relatively flat distribution. 
 
Figure 5: Distribution of Monthly Returns for the S&P 500 

---

### Page 11

  
                                                                                      www.evestment.com | 9 
 
Skewness and kurtosis are important because few investment returns are normally distributed. Investors 
often predict future returns based on standard deviation, but such predictions assume a normal 
distribution. An investment’s skewness and kurtosis measure how its distribution differs from a normal 
distribution and therefore provide an indication of the reliability of predictions based on the standard 
deviation. As Figure 6 highlights, two investments with very different distribution profiles can have the 
same mean and standard deviation. Therefore, it is useful to consider other methods for predicting 
returns. 
Source: “An Introduction to Omega, Con Keating and William Shadwick, The Finance Development 
Center, 2002 
Table 1 summarizes the key characteristics of a return distribution. 
 
 
 
Figure 6: These two distributions have the same mean and standard deviation. 
-20 -10 0 10 20 30 40 
Table 1: Return Distribution Characteristics 
NAME MOMENT COMMON NAME CHARACTERISTIC PREFERENCE 
Mean First Expected Return Balance point of the area Higher values with higher 
under the distribution moments constant 
Standard Deviation Second Volatility Measure of the width Lowest value to meet 
(variance) (dispersion) requirement 
Skewness Third Fat tail Measure of symmetry Positive 
Negative downside, 
Kurtosis Fourth Fat tail Measure of shape, tall positive upside 
or flat (Note: Kurtosis for a 
normal distribution is 3) 

---

### Page 12

  
                                                                                      www.evestment.com | 10 
 
Predicting Returns using Monte Carlo Simulation 
One method that can be used to predict returns is Monte Carlo simulation. Monte Carlo simulation is a 
method of generating thousands of series representing potential outcomes of possible returns, 
drawdowns, Sharpe ratios, standard deviations and other investments statistics of a specific investment 
or portfolio. The simulation calculates the uncertainty of a portfolio’s returns given its range of potential 
returns. Software that uses this simulation method can assess the probability of an individual achieving a 
retirement objective (and/or other financial objectives), given an investment portfolio’s specific asset 
allocation. 
Monte Carlo simulation using a bootstrapping technique allows for both skewness and kurtosis to be 
preserved. The bootstrapping technique involves resampling the actual data rather than assuming a 
normal distribution like standard deviation does. Monte Carlo simulations randomly construct a 
distribution of many possible returns for a portfolio over a specified time horizon. Thousands of possible 
results are calculated, and a probability profile is constructed for the various statistics. 
To see how this works, we can look at the stock market crash of 1987. From the period of January 1975 
to August 1987, the largest drawdown for the S&P 500 Index was -16.52%, and the average return was 
19.45%. Based on these numbers, few investors would have anticipated the crash of October 1987. 
However, using Monte Carlo simulation, we can see that there was the possibility of a market crash even 
in August 1987. Figure 7 shows the results of 10,000 Monte Carlo simulations on the S&P 500 Index. 
Note that the 99th percentile indicates a possibility of a 28.83% drawdown. This percentile indicates that, 
however remote, there is the possibility of a significant drawdown, one which historical returns and 
standard deviations do not predict.  
 
Figure 7: Returns and Monte Carlo 
PORTFOLIO PORTFOLIO BENCHMARK BENCHMARK 
MAXIMUM DRAWDOWN SIMULATION HISTORICAL DIFFERENCE SIMULATION HISTORICAL DIFFERENCE 
Number Simulations 10,000 10,000 
Mean 12.24% 8.47% 
Median 11.13% 7.98% 
Standard Deviation 5.21% 3.95% 
Maximum 46.34% 16.52% 29.82% 35.54% 19.27% 16.27% 
Minimum 1.50% 16.52% {15.02%) 0.70% 19.27% (18.57%) 
99th Precentile 28.83% 16.52% 12.31% 21 .05% 19.27% 1.77% 
95th Precentile 22.22% 16.52% 5.70% 16.08% 19.27% (3.19%) 
90th Precentile 19.21% 16.52% 2.69% 13.69% 19.27% (5.58%) 
80th Precentile 16.12% 16.52% {0.40%) 11.27% 19.27% (8.00%) 
75th Precentile 14.99% 16.52% {1.54%) 10.47% 19.27% (8.80%) 
70th Precentile 13.99% 16.52% {2.53%) 9.82% 19.27% (9.45%) 
60th Precentile 12.39% 16.52% (4.13%) 8.70% 19.27% (10.57%) 
50th Precentile 11 .13% 16.52% (5.39%) 7.98% 19.27% (11 .30%) 
40th Precentile 10.10% 16.52% {6.43%) 6.95% 19.27% (12.32%) 
30th Precentile 9.11% 16.52% (7.41%) 6.04% 19.27% (13.23%) 
25th Precentile 8.71% 16.52% (7.81%) 5.51% 19.27% (13.76%) 
20th Precentile 8.19% 16.52% {8.33%) 5.16% 19.27% (14.11 %) 
10th Precentile 6.44% 16.52% {10.08%) 4.10% 19.27% (15.17%) 
5th Precentile 5.74% 16.52% {10.78%) 3.29% 19.27% (15.98%) 
1st Precentile 3.89% 16.52% {12.63%) 2.40% 19.27% (16.87%) 

---

### Page 13

  
                                                                                      www.evestment.com | 11 
 
Figure 8 shows the results of a Monte Carlo simulation that was run as of 6/30/2011.  Each bar 
represents the range of worst potential returns which have a 10% probability of occurring. As can be 
seen in the chart, from 1975 to 2001 the S&P 
500 Index never had a 3 year to 10 year period that fell within the range. However, as of June 2011, the 
S&P 500 Index had experienced its worst performance in over a 25 year history. This example indicates 
that although there may be a discrete probability that an event might occur, it does not specify exactly at 
which time it will occur. 
 
 
 
 
 
Figure B: 10% Confidence Levels for the S&P 500 
20 .00% ----------------------------------------
·S0 .00'6 ----------------------------------------
1 Year 3Year S Year 7 Year lOYe ar 
- 10th Percentile - Minimum Prio r 6·200 1 -a- Prior 6-2004 Asof June 2011 

---

### Page 14

  
                                                                                      www.evestment.com | 12 
 
II. Risk Statistics and Risk-adjusted Statistics 
Many investors approach manager selection and analysis with pre-conceived statistical prejudices based 
on a misunderstanding of statistics. In many cases, it is because they’ve been led to believe that a certain 
statistic measures something that it does not. Others encounter difficulties trying to use a pre -defined 
toolkit of investment statistics because they’ve been led to believe that those are the right statistics to 
choose. It is important to remember, however, that investors have different notions of risk. To some, risk 
is the uncertainty of achieving an expected return. To others, it is not achieving 
a minimal  acceptable  return  (MAR). Still others define risk as flat-out losing money. To illustrate this 
point, let’s look at how many investors use standard deviation to help them identify “strong” investments. 
Standard Deviation 
Investors sometimes begin a quantitative screening by stating that they want a fund with a “low risk.” 
Because of the historical ties between risk and standard deviation in the world of traditional investments, 
they equate high standard deviation with high risk, and then use standard deviation as a comparative 
statistic. However, in truth, standard deviation is merely a statistic that measures predictability. A high 
standard deviation means that the fund is volatile, not that the fund is risky or will lose money, while a 
low standard deviation means a fund is generally consistent in producing similar returns. 
A fund can have extremely low standard deviation and lose money consistently, or have high standard 
deviation and never experience a losing period. For example, without looking at the returns the fund in 
Figure 9 exhibits a return pattern with overall consistency, which results in a low annualized standard 
deviation of 3.8%. 
 
 
Figure 9: Standard Deviation as a Risk Statistic - Take I 
Fund with Low Standard Deviation of 3.8% 
1-r------------------------------------
6 +------------------~----------------
5 +------------------ Hf-----------------
4 +-------------------rt m-----------------
3 +------------------
2 +-----------------, ,,... 
0 -'----------------'-''-'U-

---

### Page 15

  
                                                                                      www.evestment.com | 13 
 
Is the fund in Figure 9 a good investment? If we assess the same chart with returns plotted on the x-
axis, the exact opposite is true. As Figure 10 highlights, this fund, while maintaining a low standard 
deviation, has a compound annual return of less than 1% (see circled area), and the fund has lost money 
almost as often as it has generated profits. 
 
Assessing funds based on standard deviation also tends to unjustly penalize funds with high upside 
volatility. The fund in Figure 11 has a standard deviation of 22.5%, which is generally considered high. 
However, the monthly returns are skewed to the upside as the result of several months of 15+% returns 
(see circled area). 
 
Figure 10: Standard Deviation as a R.isk Statistic - Take II 
Fund with Compound Annual Return of Less than 1 % 
7.....-----------------------------------------
6 +-------------------- ~ -------------------
s +-------------------- ...tt1--------------------
4 +--------------------, -ffft-------------------
l -t----------------------1 -rtttt"TT------------------
2 -t------------------- Tirtffttlrnt-------------------
t +------ --.--.--IIH, , ~ ---
0 -fmnmmrnrrrrrmrnmmTITTTmnlTTTTTTTTTmrnmTTnn,,mmmmrmnTITTJrrltr1TI1>Nfr'11'1'iWll¥l!ITTTT11TTTT1TJT1TTTITTTTmnmrm,;mrnmrnnrmmmmnnmTmTmmmrrmmmmn ........ ................... .. ........ ,, .... ,,.. ........ ........ .. ...... i ift 'i l l l t ~ 'ifi ~ " 'f '~ i "fi" 
!~~~~~~~~!~~~~!~~~ ~~~t ~~ON~~ON~~ON~~ON~ 
vif/lt'ro'i..:iOailDU)U'i~f'Wi..iOaio510ln"'!f PotOON4¥i~u\...:aSci0Nroi1iU'i~a:icicit-ifYi~ ~~~~~~7~":~7'7'7 • ' • '' ' • .. ..,. ...... .-4.,...,.rtNNNN 
8 
Figure 11: Standard Deviation as a Risk Statistic -Take Ill 
Fund with High Annualized Standard Deviation of 22.5% 
] +-------------------- ~~--------------
6 +----------------- ~ ------<11----------------
s 
.f +---------------- ~ ---- ----11--~ -------------
3 +---------------- ----,-- - ----<11-----. - ------------
z .....-------------- ...- - ~--.--.- .-11--¼-l1-r------------

---

### Page 16

  
                                                                                      www.evestment.com | 14 
 
One of the main differences between traditional return analysis and absolute return analysis is accepting 
the fact that volatility is good, provided it is on the upside. Indeed, most investors should be less 
concerned with upside volatility, and consider downside deviation as a better measure of a fund’s ability 
to achieve its return goal. For this reason, investors should acquaint themselves with downside deviation . 
Downside deviation introduces the concept of minimum acceptable return (MAR) as a risk factor. If a 
retirement plan has annual liabilities of 8%, the plan’s real risk is not earning 8% – not whether it has a 
high or low standard deviation. 
Downside deviation considers only the returns that fall below the MAR, ignoring upside volatility. As 
Figure 12 illustrates,  if the MAR is set at 8%, downside deviation measures the variation of returns below 
this value. 
 
So, with standard deviation out of the equation, what statistics can we use to compare funds? While fund 
returns may seem useful, they do not consider the investment’s risk. Therefore, investors should always 
use risk-adjusted statistics such as the Sharpe, Sortino, Sterling or Calmar ratios. 
Sharpe Ratio 
The Sharpe ratio is the best-known risk-adjusted statistic. You calculate an investment’s Sharpe ratio by 
taking the average period return, subtracting the risk-free rate, and dividing it by the standard deviation 
for the period. 
 
This calculation generates a number we can use to compare investments. Note that for meaningful 
comparisons, all comparative investment statistics must be calculated over the same time period.
Figure 12: Minimum Acceptable Return (MAR) 
8000" ~------------------------------------------------------------
Good Returns 6000% +-------------- ,._ _____________________________________________ _ 
-40 0016 +-------------------------------------------------------~ cv----~ 
-6000'6 ~-----------------------------------------------------------~ 
Jan-75 Jan-n Jan-79 Jan-85 Jan-89 Jan -91 Jan-9 3 Jan-9 5 Jan-97 Jiil'l-99 
- S&PS0012 · Morrth RP!turn -a- MAR - Me11 n~t11rn 
Sharpe Ratio = Mean - Risk Free Rate 
Standard D evia1io n 
Jan-01 Jan-0 5 Jan-(]5 Jan-07 Jan-09 Jan-11 

---

### Page 17

  
                                                                                      www.evestment.com | 15 
 
Example: Let’s compare two investments, Fund A and Fund B. Fund A has a return of 10% and standard 
deviation of 8%, while Fund B has a return of 20% and standard deviation of 16%. If the risk- free rate is 
4%, Fund A has a Sharpe ratio of 0.75, and Fund B has a Sharpe ratio of 1.0. 
 
Comparing the Sharpe ratios, Fund B would have been the better investment because: 
• If we invested $1,000,000 in Fund A, with a 10% return, we would have $1,100,000 after 1 year. 
• If we invested $500,000 in Fund B, with a 20% return, and $500,000 in a bank account with a 
4% return, we would have $1,120,000 after 1 year. This is called de-leveraging. 
According to Sharpe, a higher standard deviation is not bad, provided it is accompanied by a 
proportionally higher return. Note that there is no such thing as a good or bad absolute number for a 
comparative investment statistic, only its relative relationship to other peers. Also note that in real world 
investing, investors do not, in fact, de-leverage. 
Sortino Ratio 
Since upside volatility will decrease the Sharpe ratio of some investments, the Sortino ratio can be used 
as an alternative. The Sortino ratio is similar to the Sharpe ratio; however it uses downside deviation 
instead of standard deviation in the denominator of the formula, as well as substituting a minimum 
acceptable return for the risk free rate. In other words, the Sortino ratio equals the return minus the 
MAR, divided by the downside deviation. 
 
Table 2 highlights the difference between the Sharpe and Sortino ratios using the S&P 500 Index and the 
Barclays Aggregate Bond Index. 
 
We can see from Table 2 that bonds have a somewhat higher Sharpe ratio than stocks (0.58 vs. 0.45). 
However, if our goal is to achieve a MAR of 10%, the Sortino ratio favors stocks (0.09). For lower MARs, 
the Sortino ratio favors bonds. 
 
Sharpe(A) = 10 - 4 = 0.15 8 
Sharpe(B) = 20 - 4 = 1.0 16 
Sortino Ratio = Mean - Minimum Acceptable Return (MAR) 
Downside Deviation 
Table 2: Differences between the Sharpe and Sortino Ratios 
PERIOD JAN 1976 TO JULY 2011 BARCLA;~:~GERATE S&P 500 INDEX WINNER 
Sharpe Ratio (5% risk-free rate) 
Sortino Ratio (MAR = 10%) 
Sortino Ratio (MAR = 5%) 
Sortino Ratio (MAR = 0%) 
0.58 
W.39 
0.93 
2.89 
0.45 
0.09 
0.54 
1.08 
Barclays Bond 
S&P 500 
Barclays Bond 
Barclays Bond 

---

### Page 18

  
                                                                                      www.evestment.com | 16 
 
Omega Ratio 
The omega ratio is a relative measure of the likelihood of achieving  a given return, such as a minimum  
acceptable  return (MAR) or a target return. The higher the omega value, the greater the probability that 
a given return will be met or exceeded. Omega represents a ratio of the cumulative probability of an 
investment’s outcome above an investor’s defined return level (a threshold level), to the cumulative 
probability of an investment’s outcome below an investor’s threshold level. The omega concept divides 
expected returns into two parts – gains and losses, or returns above the expected rate (the upside) and 
those below it (the downside). Therefore, in simple terms, consider omega as the ratio of upside returns 
(good) relative to downside returns (bad). 
Omega Ratio - The Omega Ratio is a measure of performance  that doesn’t assume a normal distribution  
of returns. 
 
 
 
 
Where 
r is the threshold return, and 
F is cumulative density function of 
returns. 
There are several ways to estimate the risk of not achieving a given return, but most of them assume 
that returns are normally distributed. However, as stated above, investment returns are not normally 
distributed, as they tend to be skewed or “fat-tailed” (i.e., there are more extreme returns than implied 
by the theoretical normal distribution). The omega calculations are important as they use the actual 
return distribution rather than a theoretical normal distribution. Thus the omega ratio and its components 
more accurately reflect the historical experience of the investment being measured. 
Since omega considers all information available from an investment’s historical return data, it can be used 
to rank potential investments in a manner specific to the investor’s threshold level. However, the omega 
decisions are not static for at least two reasons: 
1. As return information is updated, the probability distribution will change and omega must be 
updated. 
2. As an investor’s threshold level changes, the rankings among comparative investments may 
change. 
Therefore, omega allows investors to visualize the trade-off between risk and return at different threshold 
levels for various investment choices. Note that when the threshold is set to the mean of the distribution, 
the omega ratio is equal to 1. 
0 
f(1-F{x))dx 
O.(r) = _ r_ l -­
f Ffx)dx 
a 

---

### Page 19

  
                                                                                      www.evestment.com | 17 
 
Figure 13a and 13b highlights the omega ratios for two different threshold levels (a 0% return and a 
10% return) for the S&P 500 Index and a range of funds (F1 to F9). Therefore, if an investor’s minimum 
acceptable return (MAR) is 10% rather than 0%, the omega rankings among the investments will 
change. For example, for a threshold return above 0%, F1 has the highest omega ratio followed by F2 
and F3, but for a threshold return above 10%, F8 has the highest omega ratio followed by F9. 
 
 
 
Figure 13a: Omega Ratio 0% 
S&P 500 Fund 1 Fund 2 Fund3 Fund4 Fund 5 Fund6 Fund 7 Funds Fund9 
TR 
Figure 13b: Omega Ratio 10% 
S&P 500 Fund 1 Fund 2 Fund 3 Fund4 Fund s Fund 6 Fund 7 Funds Fund9 
R 

---

### Page 20

  
                                                                                      www.evestment.com | 18 
 
A key question to consider is how the Omega Ratio compares when ranking Omega Ratio relative to more 
commonly used Statistics. Table 3 summarizes the return data for Fund A and a mix of asset class 
benchmarks. The table is sorted on Sharpe Ratio, and the Omega Ratio has a 1% monthly return 
threshold. When looking at the rankings, Bonds appear to be a good choice when looking at Sharpe 
Ratio, however the Bonds have the lowest Omega Ratio at the 1% monthly return threshold. Fun d A 
provides the highest Sharpe and Omega ratios and has the smallest drawdown. 
 
Table 3: Omega and Common Investment Statistics 
STANDARD COMPOUND OMEGA SHARPE MAXIMUM 
NAME DEVIATION ROR RATIO (1 %) RATIO DRAWDOWN ALPHA BETA 
Fund A 6.51% 19.58% 2.03 2.59 -2.81% 19.87% -0.05 
Barclays Aggregate Bond Index 3.80% 6.36% 0.29 1.29 -3.82% 6.41% 0.03 
S&P 500 TR 22.16% 2.08% 0.75 0.14 -51.81% 3.72% 1.11 
Russell 2000 Index 24.48% -0.51% 0.72 0.05 -54.08% 1.58% 1.21 
Nasdaq Composite Index 19.15% -1.06% 0.61 -0.03 -50.95% 0.00% 1.00 
MSCI EAFE 23.01% -3.77% 0.62 -0.11 -56.68% -2.00% 1.11 

---

### Page 21

  
                                                                                      www.evestment.com | 19 
 
Because the Sharpe ratio is calculated from return data that has been averaged or annualized, the 
resulting ranking of the investments do not include higher levels of information specific to the shape of 
the distribution of the underlying return data. Therefore, it is reasonable to conclude that the observed 
differences in rankings are due to the higher levels of information contained in the Omega calculations. In 
effect, Omega as a risk-adjusted measure provides investors with additional information to better 
understand the risk/reward characteristics encapsulated within an investment’s historic returns. 
Figure 14 illustrates the omega ratios for five different investments (Funds A-E) for a 12-month holding 
period. The two selected thresholds are a minimum acceptable return (MAR) of 2% (dashed purple line) 
and a target return of 8% (solid purple line). If a 2% downside is an investor’s primary concern, then 
Figure 14 shows that there is considerable difference between the funds, as Fund A (the red line) has a 
much better chance of exceeding the downside (i.e. it has a higher omega ratio at 2%). 
However, there is less difference between the funds as far as earning a target return of 8%. This means 
that choosing between the funds should be based more on the downside risk than on the expected 
return. The 8% target is close to the crossover point of all the funds. The Omega ratio is a useful 
investment tool because it can be used in a compact way to show how different investment options relate 
to a target return and to a MAR. 
 
 
0 
C'4 
C! .,.. 
.,, 
Q 
0 2 
Figure 14: Omega Ratio~. Ta~e II 
Omega Ratio: 12-month Holding Period 
4 6 8 
- FundA 
- FundB 
- FundC 
- FundD 
- FundE 
10 

---

### Page 22

  
                                                                                      www.evestment.com | 20 
 
Figure 14 used a 12-month holding period, which is appropriate for short-term expectations. However, 
Figure 15 uses an investment horizon of 5 years (60-month holding period), and shows that downside 
risk is less of a consideration for this period. The main decision is the target return. Once again, it is 
essential to consider the specific time period when analyzing investment returns. 
 
~ 
Q 
N 
0 
Qi 
.... 
0 =-.; ui Ill 
a:: 
~ 
Ol 
Q,)• 
E ~ 
0 N 
C! .. 
In 
0 
2 4 
Figure 15: Omega Ratio - Ta.ke Ill 
Omega Ratio: so-month Holding P,eriod 
6 8 10 
- Fund A 
Fund B 
- FundC 
- Fund D 
- Fund E 

---

### Page 23

  
                                                                                      www.evestment.com | 21 
 
Drawdown Analysis 
Drawdown analysis can be an excellent way to screen investments. A Maximum Drawdown is the 
maximum amount of loss from an equity high through the drawdown and back to the point the equity 
high is reached again. There could be many drawdowns over a given date range and will be listed 
starting with the maximum drawdown. Figure 16 illustrates the maximum drawdown over the period 12-
2009 to 07-2011, although it is not the only drawdown. Maximum drawdowns being analyzed on 
numerous investments should be calculated over the same date range. 
 
 
 
 
 
 
 
 
 
 
 
 
Figure 16: Maximum Drawdown Example for the S&P 500: 
December 2009 to July 2011 
1400 --------------------------------------------
Recovery 
Valley 

---

### Page 24

  
                                                                                      www.evestment.com | 22 
 
 
In addition, it is important to remember that drawdowns are relative to return. The S&P 500 Index in 
Figure 17 exhibits drawdowns that would give most investors pause. However, if you chart the losses and 
time underwater versus the returns of the fund (Figure 18), some investors might find the fund worthy of 
additional consideration. 
 
There are numerous reasons for a drawdown, including market stress, giving back part of unrealized 
profits after a large increase in equity, or just poor trading. From a quantitative perspective, however, it 
is important to analyze the reasons that caused a particular drawdown, and not exclude a fund based on 
just absolute numbers. 
i 
0 
j 
f!! 
C 
0% 
-10% 
-20% 
-30% 
-40% 
-50% 
-60% 
i 
0 
'C 
:,: 
f 
C 
c.. c.. Ill Ill 
:I :I 
.:., .:., 
(II ...... 
0% 
-10% 
-20% 
-30% 
-40% 
-50% 
-60% 
c.. Ill ::, 
I 
...... 
(11 
c.. c.. c.. c.. 
Ill Ill Ill Ill 
:I :I :I :I 
.:., clo clo clo co .... w (II 
c... c... c... c... Ill I» Ill Ill ::, ::, ::, ::, 
I I 
& & ...... ...... ...... U> .... w 
Figure 17: Underwater Chart 
c.. c.. c.. c.. c.. c.. c.. c.. c.. c.. c.. c.. c.. Ill Ill Ill Ill Ill Ill Ill Ill Ill Ill Ill Ill Ill 
:I :I :I :I :I :I :I :I :I :I :I :I :I 
clo clo cl, cl, cl, cl, co 6 6 6 6 6 .:.. ...... co .... w (II ...... co .... w (II ...... co .... 
■ Drawdown 
Figure 18: Drawdown Relative to Return 
$70,000 
$60,000 
$50,000 
$40,000 ~ 
$30,000 3i: 
$20,000 
$10,000 
$0 
c... c... c... c... c... c... c... c... c.. c... c... c... c... c... 
Ill I» I» Ill Ill Ill Ill Ill I» Ill Ill Ill Ill Ill ::, ::, ::, :::, ::, ::, ::, ::, :::, :::, ::, ::, :::, ::, 
& & 
I I I I I I I 
6 
I 
6 ' 
I 
m IO U) U) U) U) C C C .... 
(11 ...... <O .... w (11 ...... U> .... w (11 ...... ID .... 
- □ rawdown - s&P500TR 

---

### Page 25

  
                                                                                      www.evestment.com | 23 
 
The Calmar and Sterling ratios provide additional comparative information for a risk-adjusted assessment 
of drawdown analysis. 
Calmar Ratio: The Calmar ratio is the annualized return for the last 3 years divided by the maximum 
drawdown during these years. 
 
Sterling Ratio: The Sterling ratio is the annualized return for the last 3 years divided by the average of 
the maximum drawdown (in absolute terms) in each of the preceding 3 years, less an arbitrary 10%. An 
extra 10% is subtracted from the drawdown as one assumes that all maximum drawdowns will be 
exceeded. 
 
Comparing Risk Statistics and Risk-adjusted Statistics 
So, let’s put all of our investment risk statistics and risk-adjusted statistics to work. Figure 19 summarizes 
the statistics of a fund, Fund C, versus the S&P 500 and Barclays Aggregate Bond Indices. 
 
 
Galmar Ratio= AlmualizedR,OR (last 3 years) 
MaximumlJrawd'own' (last 3 yea.rs) 
Sterling Ratio= An'~uafizedRDR (last 3 years) 
absolute (A verag eD rawdown - 1 0%) 
Figure 19: Risk Statistics and Risk-Adjusted Statistics 
RISK TABLE FUND S&P 500 TR BARCLAYS AGGREGATE BOND INDEX 
Compound ROR 0.79% 0.19% 0.47% 
Risk Statistics Arithmetic Mean 0.87% 0.30% 0.47% 
Standard Deviation 4.19% 4.66% 1.01% 
Semi Deviation 3.59% 5.38% 1.03% 
Gain Deviation 3.38% 2.49% .71% 
Loss Deviation 2.15% 3.76% .56% 
Downside Deviation (10.0%) 2.62% 3.85% .90% 
Downside Deviation (5.0%) 2.40% 3.65% .67% 
Downside Deviation (0%) 2.19% 3.46% .48% 
Losing Streak -8.9% -14.31% 0.00% 
Max Drawdown -17.74% -50.95% -3.82 
Sharpe Ratio (5.0%) 0.11 -2.32% 6.33% 
Risk-Adjusted Sortino Ratio (10.0%) 0.00 -15.81% -36.64% 
Statistics Sortino Ratio (5.0%) 0.16 -5.98% 8.76% 
Sortino Ratio (0%) 0.36 -5.46% 97.96% 
Sterling Ratio 0.16 0.02 .59 
Calmar Ratio 0.19 0.01 1.97 
Skewness 0.79 -0.83 .15 
Kurtosis 1.79 1.67 1.18 
Tail-Risk Omega Ratio (1 %) 0.88 0.64 0.24 
Statistics Modified VaR (95%) -4.87 -8.26 -1.12 
Modified Ell (95%) -6.20 -10.64 -1.75 

---

### Page 26

  
                                                                                      www.evestment.com | 24 
 
III. Correlation and Regression Analysis 
We have all heard investment managers discuss their low correlations, high alpha, and low beta, but 
what is the real meaning of these terms? All of them relate to how different investments react relative to 
one another. 
• The correlation coefficient (R) measures the extent of linear association of one or more funds or 
indices. 
• Alpha is a measure of value added by an investment relative to the market (i.e. an index) or to 
another investment. 
• Beta is a measure of the volatility of an investment relative to the market (i.e. an index) or to 
another investment. 
• The coefficient of determination (R
2) measures how well the regression line fits the data. The R2 
is the only measure that attempts to be predictive. The regression line is a graph of the 
mathematical relationship between two variables. 
In Figure 18, the regression line is the line of “best fit” drawn through a scatter plot, and represents a 
linear relationship between two investments. 
The Correlation Coefficient (R) 
The correlation coefficient can range from -1 to +1. As Figure 20 illustrates, a correlation value near +1 
indicates a high positive correlation between two investments. If one investment has positive returns 
during a period, it is highly likely that the other investment’s returns will also be positive. 
 
 
Figure 20: Correlations between Investments 

---

### Page 27

  
                                                                                      www.evestment.com | 22 
 
As Figure 21 illustrates, if two investments have a correlation of -1, the investments are negatively 
correlated, so if one investment has a positive return one month, it is likely that the other investment will 
have a negative return for that month. 
 
 
Finally, as Figure 22 illustrates, if an investment has a correlation approximately equal to 0, the 
investments are not correlated to one another, and move independently. If one investment is up, the 
other could be either up or down. If one investment is down, the other could be either up or down. 
 
_,,. 
♦ ♦ ♦ 
"' 
·2% 
• _,. 
♦ 
Figure 21: Correlations between Investments - Take II 
Perfect Negative Correlation = -1 
Figure 22: Correlations between Investments - Take Ill 
No Correlation: R = -0.01 
... 
♦ T • 
• ♦ ♦ 
• • .... 
i 
T -·-• ♦ ♦ .... • 
♦ ♦ 
♦ • ♦ • 
♦ ....... 
♦ 
• •• ♦ 
•• , .... ♦ 
.,,t ♦ • ... 
•'" q ' 
·t ,,,. 
• •• 
♦ 
♦ ♦ 
T . 
• ♦ 
• 
♦ 
♦ 
"' 
♦ 
♦ 
• • 
"' . '" ' " 
• ♦ 

---

### Page 28

  
                                                                                      www.evestment.com | 23 
 
Alpha and Beta 
Alpha and beta are also related to the regression line. As Figure 23 illustrates, alpha is the Y intercept of 
the regression line. In other words, if the benchmark returned 0%, the Y intercept would tell us what the 
investment could be expected to return. In Figure 23, the alpha is 2.23%. That means if the benchmark 
returned 0%, we would expect our investment to return 2.23%. 
Beta is the slope of the line and measures the volatility of a particular investment relative to the market 
as a whole. (Note: The market can be defined as any index or investment.)  Beta describes an 
investment’s sensitivity to broad market movements. For example, in equities, the stock market (the 
independent variable) has a beta of 1.0. An investment with a beta of 0.5 will tend to participate in broad 
market moves, but only half as much as the overall market. 
 
The Coefficient of Determination (R2) 
It is important to consider the coefficient of determination (R2) when evaluating a fund’s alpha or beta. 
The R2 measures how well the regression line actually fits the data. A high R2 value means that the 
regression line closely fits the data, as in the example in Figure 23 (R2 = 0.9373). However, if R2 is low, 
the regression line does not fit the data, and any calculations based on regression line analysis, including 
alpha and beta, become less meaningful as the R2 value drops. 
.a" ·61< 
""" 
• 
• • 
• 
Figure 23: Investment's Alpha and Beta - Take I 
Meaningful Results for Alpha and Beta (High R' of 0.9373) 
11" 
10" 
.,. 
-4% 
.,,. 
·•" 
·7% 
·8% 
·9% 
-10% 
Alpha 
The V Intercep t 
21< 
• 
... 61< a" 
Beta 
The Slope 
10% 
• 
12" H I< 

---

### Page 29

  
                                                                                      www.evestment.com | 24 
 
 
As Figure 24 illustrates, the returns have little relation to the regression line, and R2 is essentially 0. 
Drawing conclusions about a fund’s alpha or beta based on this particular regression analysis would yield 
no meaningful results. 
 
Benchmark Ratios 
Benchmark ratios are also useful in evaluating investments. These ratios provide information in a single 
number about a fund’s performance relative to a benchmark. Obviously, the selection of an appropriate 
benchmark is critical. 
Active Premium: The simplest benchmark ratio is the “active premium,” which takes the fund’s 
annualized return, and subtracts the benchmark’s annualized return to yield the fund’s gain/loss that is 
over/under the benchmark (i.e., the excess return). Positive active premium is good, while negative 
active premium is generally bad. In Table 4, the active premium of -1.31% tells us that, overall, the fund 
underperformed the index. 
 
 
 
 
-30.0(1% -20.00% 
Active Premium 
-1.31% 
• 
• 
• 
• 
Up Capture 
130.91 % 
• 
• 
. 0 .00% 
• 
• • • , .oo .. 
.. , 
• • • • 
-5.00% 
• 
• 
-10 .0 0'iE, 
-15.00% 
• 
-20 .009' 
Figure 24: I nvestment"s Alpha and Beta - Take II 
•• • • • • •• • • .. • • • • • • • • 
30.00% 40.00% S0.00'-' 
• • • • • • • • Y=-.00002 9ll:+,0131 
.. , 
• • 
8 8 
Table 4: Investment Benchmark Ratios 
50.00" 
Down Capture 
101.08% 
Up Number 
92.00% 
Down Number Up Percentage Down Percentage 
92.50% 54.50% 30.83% 
Market 
45.63% 

---

### Page 30

  
                                                                                      www.evestment.com | 25 
 
 
Up and down capture ratios are also helpful when evaluating investments. 
− Up Capture Ratio: The up capture ratio is a measure of a fund’s cumulative return when the 
benchmark was up, divided by the benchmark’s cumulative return when the benchmark was up. 
The greater the value, the better. 
− Down Capture Ratio: The down capture ratio is a measure of a fund’s cumulative return when 
the benchmark was down, divided by the benchmark’s cumulative return when the benchmark 
was down. The smaller the value, the better. 
− Up and Down Number Ratios: Up and down number values measure the percentage of time 
that an investment moves in the same direction as the markets. In Table 4, approximately 92% 
of the time the fund moves up and down with the benchmark. Unfortunately, this statistic doesn’t 
yield much information about the fund’s relative outperformance, so we combine these numbers 
with the proficiency ratios (up/down market percentage ratios) to glean more information about 
the fund. 
− Up Market Percentage Ratio: The up market percentage ratio is a measure of the number of 
periods that an investment outperformed the benchmark when the benchmark was up, divided 
by the number of periods that the benchmark was up. The larger the ratio, the better. In Table 
4, the fund outperformed the index 54.5% of the time when the index was up. 
− Down Market Percentage Ratio: The down market percentage ratio is a measure of the 
number of periods that an investment outperformed the benchmark when the benchmark was 
down, divided by the number of periods the benchmark was down. The larger the ratio, the 
better. In Table 4, the fund outperforms the benchmark only 30% of the time when the 
benchmark was down. This would not be considered strong performance for a hedge fund 
manager. 

---

### Page 31

  
                                                                                      www.evestment.com | 26 
 
IV. Peer Group Analysis 
Peer group analysis is the final piece of the basic investment quantitative toolkit. It allows investors to 
see how a particular fund ranks over various periods compared to funds using the similar investment 
strategies. 
Top Quartile Performance 
The fund in Figure 25 ranks in the top quartile of its peers over all of the trailing periods measured. This 
means that, out of all of the funds that manage money in the same investment strategy, the selected 
manager ranks in the top 25% of his/her peer group. If we assume an investment universe of 100 funds, 
this manager would rank within the top 25 funds in terms of recent returns for that investment strategy. 
You can perform peer group analysis on numerous statistics, including compound annual return, 
drawdown, Sortino ratio, Sharpe ratio, percent profitable months, etc. Managers who consistently rank 
high among their peers in a number of statistical categories are generally considered better managers. 
 
 
 
 
25% 
20% 
15% 
5 
10% 
" "' i 5% 
" ~ 
" .. 
O'II, 
-5% • 
· 10% 
· 15% 
•20% 
1H Q 611 
Figure 25: Peer Group Analysis - Take I 
Recent Returns: Top Quartile Performance 
... 
YTD lY 2Y 3Y 
:5th to 25th Pilf'Clfttile 
,ad,to2'thP•rmntiliR 
7~ to 50th P•l"Clflti~ 
• 9.5th to 7,th P11trantHe 
• Bendtm•rk 2 
&Be.ndvn~ricl 
SY 7Y lOY . ..... ud 

---

### Page 32

  
                                                                                      www.evestment.com | 27 
 
Bottom Quartile Performance 
Figure 26 shows the same fund measured against its peers based on calendar years instead of recent 
periods. The fund ranks in the bottom quartile on more than one occasion. This means that, out of all of 
the funds that manage money in the same investment strategy, the selected manager ranks in the 
bottom 25% of his/her peer group. If we assume an invest- ment universe of 100 funds, this manager 
would rank within the bottom 25 funds in terms of calendar year returns for that investment strategy. 
Although the fund looked good based on trailing periods (Figure 25), Figure 26 illustrates that there had 
been no consistency in top performance over the years. 
 
Peer group analysis is important for a number of other reasons. Perhaps its best use is in screening data 
to find new investment managers. All too often, investors let arbitrary wish lists govern their screens. 
Seeking a manager with a 
3-year track record, no losing months, an annualized return greater than 15%, and a Sharpe ratio greater 
than 2 does not guarantee that such a manager exists, or if they do exist, that they will be open to new 
investments. To select the best funds from a quantitative standpoint, it is best to think in terms of 
percentiles rather than absolutes, and herein lies the value of peer group analysis. Therefore, your goal 
should be to find the best fund manager comparatively, rather than search for an investment fantasy. 
Manager Search Criteria 
Assume you are searching for a hedge fund of funds (FOF) and require a MAR of 10%. You can complete 
the following 5-step process: 
Step 1 - The first step is to narrow the investment universe to include only FOFs. Starting with 
a large hedge fund universe comprised of all strategies we searched for FOFs, narrowing our hedge fund 
universe from approximately 1,700 funds to about 250 funds. 
Step 2 – Select the Statistics for Screening: Using your new knowledge of statistics, select realistic 
14D'!I> 
120'111 
100'111 
8D'!I> 
~ 
'ii 60% .. 
~ 
V 
~ 
• V 40'111 .. • ♦ 
20'111 
.. 
0'111 
-20% 
-40'111 
-60'111 
211 11 21110 2009 
Figure 26: Peer Group Analysis - Take II 
Calendar Year Returns: Bottom Quartile Performance 
2008 2007 2006 200S 2004 2003 
,thto 15th Pllf'IX.ntile 
50th to 25th Perotntile 
r.itfl to 50th P•rmntil• 
1195th to 15th P•rwntile 
• 
• BMmma.t.:2 
♦ 
• &8111ndami11'kl 
■ P NXllct 
2002 

---

### Page 33

  
                                                                                      www.evestment.com | 28 
 
statistics to use in your screens. For example, if you’ve developed an investment mandate that dictates 
you need high returns and are less concerned about drawdowns, you might use the compound annual 
return, rolling returns, and Sortino ratio (MAR 10%) rather than drawdown  statistics.  If losses are your 
paramount concern, you might consider the Sortino (MAR 0%) ratio, drawdown, Sterling and Calmar 
ratios. 
Step 3 – Determine the Investment Period: To ensure you compare apples to apples, screen for 
funds with similar track records. Because the markets experienced a significant stress point in 1998, 
search for funds that started in or before January 1998. This track record narrows our sample to about 
75 funds. 
Step 4 – Select Funds that Meet the MAR: Next, we search for all funds with an annualized return 
greater than 10% (our MAR). These actions reduce our universe  to 36 funds. 
Step 5 – Rank the Funds by Percentiles and Assess Sharpe Ratios, Maximum Drawdowns, 
Sortino Ratios and Correlations: Rather than search all 36 funds for the “wish list” criteria, we first 
rank the funds by percentile to determine reasonable search characteristics. Since the required MAR is 
10%, we do not rank on annualized return, so we first assess the Sharpe ratio, as the Sharpe measures 
risk vs. reward and a manager with a strong risk-reward profile is part of our mandate. 
 
Next, we screen for maximum drawdown, because our particular investment mandate dictates that we 
want to limit drawdowns, even if it means limiting some upside potential. In Figure 28, we see that to be 
in the top quartile for maximum drawdown, funds must have lost less than -5.50% during their 
maximum drawdown. 
Pttttnlll 
.. 
'1 
8,8 
le 
~ 
it ., 
t2 
t! 
•• to 
1t 
71 ,. 
11 
11 
1' 
11 
( 
~T 
r~n.,,,. 
('~A411AM 
r c-.i-s..1 .• 0,:1 
.. T~ 
r-1 ... w-
(' o...w.on .. 11 ..... 
<" 1"-8f1141ed8-
rv-
r~!I ... 
Figure 27: Manaaer search Criteria • Take I 
Comparing Sharpe Ratios 
flj1Ui14>14 
~-~ !J! - ~M 
U$'f. l38'1r. 
l;tl'J, 1.1"4 
USS 0~ (lltl) 
21~ 11ft I l'I 
1.$111, G.11 (11 1) 
2.()8,r, I iG'J. (IHO) 
307!1, ,".,. 0'6 
UK 2.13 1.119 
,094 1t7 o,u 
2&3'1, ltS'lo 48 092 
l&S'f. utr. i5 us 
un 4 :mr. ,4S 2.41 
uar. , __ 1.42 OU 
2osr. 1;54111. I 10 ,., 
)$4<11, :u,n; 0 4(1 
Ul'f. lffii 082 
301'11, Hitt. O;tS 
H1r. J-6();1; 0 St 
Pw,od 
(' R•dR- (' A'IJ~ll.., (' S"-R.lio ,._., 
r11-ci.... f'&IIISIIIOtv rs~RP ro......,, 
r11...-0Lo<t (' t.o,;, S4cl10.., f't,in,o,R ... ~ 
('Gwvlo,i r a.~ r s..,,.11o1,o 
~ ('"-- r,.,,,- ,_ ("--1) .. 
('~, f"M•O,...;.... r1.o,,,,ps..... IIIC RI\NGE 
r11•-
r......, r ~ 
H5 
• u 2.&! 
o, 1 ll 
no 2'2 
HI 351 
l 41 50 
JU 51~ 
UI Ht 
HS 818 • 2'1 
l .U 179 508 
,n SH 05 
ns 09 Hl 
LOO Ui 33! 
Ut 4111 IU 
HS HO HI 
J 00 &.19 31] 
2.11 s.o 61M 
··~ 
• ' 
! 
a-M--, 
Fltrfr.!inrlUII 
~ 
e,,,. 
""'"''" bi (" -fll r RS""°od 
----:.:.:.~-===-------' 

---

### Page 34

  
                                                                                      www.evestment.com | 29 
 
 
Then, we focus on the Sortino ratio to ensure we give downside deviation its due without sacrificing any 
upside that might be generated by a high standard deviation with good returns. As Figure 29 illustrates, 
to be in the top quartile for the Sortino ratio (MAR of 10%), funds must have a Sortino ratio greater than 
a 0.69. 
 
Figure 28: Manager Search Criteria - Take II 
Comparing Maximum Drawdowns 
..!Cl 
Pffltfl Ril T-
-
a.in Lon 0-00. .. 
An,11,rMiztd o.wi-~~ ,.~ .. • ,o,, IM U2'11 us, ., ,~ Uni • u, 15" 
N 2,n. HJ'!li 2-
• • ◄ 2!1 1.31"4 ,.~ 
fl C,Sl'II ) Hl"J; I :It'll US1fo 
•• •1"r. ,.,. , 50'r. 
11 1-M'!li 
·-
UM, 
~ r.an. 104 ' • :1!1'11 U6'11 
,2 ,_ lto• 02'!1 ?7K ,, t.Ol"llo IM 2&1!1 . ,.,. 
IC) 111H, l .31 .. I TJ'!li 3-
1'l ]Q,.. 205\lli 1118'6 USS ,, 111'1, 145,i; IU'II )Ol!I, 
" 
l 16'11 I t7!1 270'llt 
11 1l. • 01'! lM'II J 
,. u IM'II 116 2.)11'1, 
,~ It , ,.,. l,GQ'li 
' ''" , .... ,. 10 . ""' ''""' 
HO<r. ns<r. ,. 12 ,., Hl'llo S.1t• Ul'lrt 
~,>1>0 p-
r -...,~ r -.,~- ('- ""'Sild°'"' r-si-o ,. _.,,_, a..-
r o,,,,,.-/lol,- r •..,~o.., r c..,,~o.. r $'1,llogR,oo r a.-.. R r e-..,.. r •-- rt-S ldO.. r e-~ 
-.. ·-
r-. (' h,lf'wd r s.....- r:::11"'3 
p_._ 
r 1,_..,_, ri-... r.....,.,_ r -o... 
r .. -. (' IIW&llGp f' MaD-. r 
-
INC 
-
.i,,. r ,_n...o111-., r """"""' r v. 
r ~- r l>lf;-,. ,. .... r (IIJ r ll~ ll<dot, C-coL• 
Figure 29: Manger Search Criteria - Take I 
Comparing Sortino Ratios 
..!Cl.<!! 
-·-
Slt<1lnf• 
10 ~ ~ -- RM 
.. 1t•• l <K •m~ u • HO 
" 
:us• 1 lt'lrt ,m H t ,o 16 • '3 
16 1119'1 74ft Un I a9 , .. '11 
"" 
&M'!li IOD'!li 75:111. 111 1-61 ue 
IS u, .• 2 12!1 I 0711, 3~ 855 ~ I~ 
.. $ CI W. •n'i ,u<r, 2 ,s HS Ul 
u Ufi'li 215~ UH~ Z It UJ • t2 
H , «• OIK 11.45'11 111 Z• H o , 
u U1'A ins I !5'11 us 1811 • ?1 
" 
:U6!1, 3121'> H:11'> HT ~3S ~ l$ 
IO u,. 2., ... ,., .. l 00 $ , , Hl 
11 UJ 28511. 131''11 U.i 5'0 J H 
18 t.S~ Sfi'II 5 25'11 1.10 71] HI 
18 )IIO'A 193'1!. 11, 11. UT u, Ht 
11 SIIII ~U'lrt 
·- "' 
l.Gt HI.I 
76 u ,. 903'1rt · • 111. 13' l .01 HJ 
I i 111111 641'11 
·-
IBa'I HI t .D:11 
1 ◄ ,.,a• ,_ ,,,, I l$ , u ~ Ill 
1, $-SI 03"" 0 4'11 1113 Ht ,S U ., 
•' 
0...,TJPO 
-r ~- r RwolA- (" .,,...5'i!C>... r -.,.R., I" M ...... liriM-.o, 
(" -~R- r ,.,..,.G-, r- G-,Sod 0.,, (' -.08-- r ~ Ari 
(" ~-- ,. . ._~. (" l!..ou, Sido.rt, r ~R ... 
-"'Aat. t- ,. _ r e..-.._ rs.,i,,.,,RMQ 
r3r-3 -
(" I " 
-
f'l l'laliMo rwoml'fflod (' Oownn,loOr, 
r o_,.,11 ......, r ~ ,- M °' ....... f" L-~ .... IM IWl(i[ 
ill<' f'"-llwcilll- r Hoc1o-
r v-
r e..-.- ('; ~ r e ... f' C-W...1R I (" R ~ ~ Cn:,!la ENI 

---

### Page 35

  
                                                                                      www.evestment.com | 30 
 
We then search our FOFs universe  for those funds with  a Sharpe ratio greater  than 1.28, less than a 
5.50%  maximum drawdown,  and a Sortino ratio greater  than 0.69. In other words, we wish to find 
FOFs with top quartile performance in all criteria categories. As a result, we find 4 funds out of 36 that 
are quantitatively the cream of the crop, given our criteria and compared with their peers.  
Another reason that investors consider FOFs is to diversify their long-only portfolios. So a final step in our 
quantitative search might be to find FOFs with a negative correlation to the S&P. When applying this 
criterion, we reduce our list of 4 to 2. 
This same 5-step search process can be completed on virtually any universe of funds, including hedge 
funds, separately managed accounts, commodity trading advisors (CTAs) and mutual funds.  Perhaps the 
most important part of the search process is to first establish reasonable search parameters. Otherwise, 
you risk setting the bar too high for any fund to hurdle, and backing down from there later. Also, 
recognize that peer group analysis is still important after an investment is made, since it provides one 
way to determine if the fund continues to offer the best investment option within a given investment 
strategy, or if other funds provide better options. 

---

### Page 36

  
                                                                                      www.evestment.com | 31 
 
V. Composite Returns: Portfolio Construction, Optimization, Simulation 
An investment in a single fund has both market risk and manager risk. By constructing a portfolio of 
funds the manager risk can be minimized. Optimization allocates among the managers in the portfolio to 
maximize the return for the investor’s risk tolerance or minimize the risk for the investor’s desired return. 
Using a Monte Carlo simulation, the investor can predict the portfolio’s future returns or at least the 
likelihood of future returns. 
Portfolio Construction 
Whether a portfolio is constructed to provide exposure to the market or targeted exposure to a particular 
region or strategy investing in multiple funds will reduce the manager-specific risk. Figure 30 
demonstrates the benefits of diversification using two asset classes, US Equities (S&P 500 Index) and 
Commodities (Barclays CTA Index), for the period January 1, 1995 through December 31, 1999. 
US 
Equities and Commodities are not perfectly correlated. The lack of perfect correlation means that their 
gains and losses occur at different times. As a result, it’s less risky to be invested in a portfolio with 
exposure to both assets classes. How much exposure the investor should have to each asset class will be 
covered in the Optimization section. 
This same principle holds true when investing in individual funds that are not perfectly correlated. The 
more funds in the portfolio the more the risk created by an individual manager is reduced. The risk that 
cannot be eliminated by diversification is the systematic risk or common sources of risk to all managers in 
the market, strategy, region and sector. At some point, there is a limit to the diversification benefit 
provided by adding an additional fund. There is a cost, both in terms of portfolio performance and 
financially, to invest in an additional fund that may exceed the diversification benefit. 
Figure 30: Power of Diversification 
100% Barclay CTA Index 
0% --'-----------_._ _________ __.._ _________ __. 
5% 3% 112". 15% 
Risk 

---

### Page 37

  
                                                                                      www.evestment.com | 32 
 
To measure the benefits of a portfolio of funds a composite return series is created. The portfolio’s 
performance consists of the underlying funds’ performance, the allocations or weights to the underlying 
funds in the portfolio and the rebalancing schedule.  
For one month the calculation of the portfolio performance is: 
Important factors in the calculation of portfolio performance are: 
Allocation (weight) – Is the percentage of capital assigned to funds in the portfolio.  Capital can be 
equally allocated across all funds in the portfolio, mandated by an investment policy or decided using 
optimization software to determine an ideal allocation. 
Leverage – The investor can increase their position in an underlying fund by using leverage. For 
example, if the position is levered 2 to 1, we are taking a dollar of investor capital and borrowing another 
dollar to invest 2 dollars in the underlying fund, effectively doubling the position in the fund. 
Rebalancing – When investing in private investments, the rebalancing schedule is typically never 
rebalanced due to the illiquid nature of the investments. Only a monthly rebalancing schedule will 
maintain the same starting allocations each month. The other rebalancing choices will allow the percent 
allocations to the underlying funds to change with the NAVs of the underlying funds until the portfolio is 
rebalanced. The common rebalancing schedules include: 
Never – allocations are applied at the start date and the assets are allowed to grow. Never 
rebalance might be used with a buy and hold strategy, when invested in illiquid assets or while 
investing in funds with lockups which will not allow redemptions. 
Annual – every 12 months the original allocations are applied. This rebalancing frequency might be 
used where the portfolio has target allocations that are maintained each year. 
Semi Annual – every 6 months the portfolio returns to the original allocations. d. Quarterly – every 
3 months the portfolio returns to the original allocations. 
Monthly – at the beginning of each month the portfolio resets to the original allocations. Monthly 
rebalancing is most commonly used when constructing a blended benchmark, e.g. 60 percent 
equities and 40 percent bonds. 
N 
P = {I F1 xW1) 
1=1 
Where P = Portfolio Return for the month 
Where F1 = Return for Fund I for the month 
Where N = Number of Funds in the Portfolio 
Where W1 = Allocation to Fund I in the Portfolio 

---

### Page 38

  
                                                                                      www.evestment.com | 33 
 
Manual – any allocation can be given to any funds at any time in conjunction with other 
rebalancing schedules. Manual rebalancing represents a subscription in a new fund, additional 
subscription in a fund currently held in the portfolio and/or a partial or total redemption of an 
existing fund in the portfolio.

---

### Page 39

  
                                                                                      www.evestment.com | 34 
 
When the portfolio is rebalanced, in effect, for the funds that did well a portion of their gains are being 
sold and these gains are being invested in the funds that had losses to bring the portfolio back to the 
original allocations. Figure 31 is an example of quarterly rebalancing. 
The portfolio starts January 1, 2011 with a capital balance of $10,000,000 equally allocated among four 
funds or $2,500,000 invested in each fund. On March 31, 2011 the funds’ allocations are no longer equal. 
Fund A = $2,643,555.25 
Fund B = $2,601,364.11 
Fund  C = $2,468,360.71 
Fund D = $2,554,751.27 
Summing the four positions gives a portfolio value $10,268,031.34.  For an equally allocated portfolio 
starting April 1, 2011, each fund’s position value should be $2,567,007.84.  Portions of Fund A and B’s 
gains are being sold and invested in Fund C and D in order to bring the portfolio back to its original equal 
allocations. At the end of each subsequent quarter the portfolio is once again rebalanced.  
 
Figure 31: Quarterly Rebalancing, Selling the Winners & Buying the Losers 
Portfolio - Additions/Withdrawals 
From January, 2011 To March, 2012 - Rebalanced Quarterly 
Date Fund A Fund B Fund C Fund D 
Jan-2011 0.00 0.00 0.00 0.00 
Feb-2011 
Mar-2011 
Apr-2011 (76,547.42) (34,356.27) 98,647.12 12,256.57 
May-2011 
Jun-2011 
Jul-2011 (54,319.34) (64,443.39) 208,615.90 (89,853.17) 
Aug-2011 
Sep-2011 
Oct-2011 41,004.18 (102,553.35) 285,669.36 (224,120.19) 
Nov-2011 
Dec-2011 
Jan-2012 (3,626.68) (91 ,557.44) 104,188.37 (9,004.26) 
Feb-2012 
Mar-2012 

---

### Page 40

  
                                                                                      www.evestment.com | 35 
 
Lack of performance – When constructing a pro forma portfolio some funds may have inception dates 
after the desired inception date of the portfolio, thus lacking several months of data. The lack of 
performance can be addressed by reallocating to other investments in the portfolio or by using backfill. 
Reallocating to other investments will proportionality redistribute the fund’s allocation to funds with 
performance until the fund does have performance. 
Backfilling adds returns from another fund or index to the fund with the later inception date. The 
following common backfill approaches are: 
Zero performance – equivalent to the percent of capital invested in the fund not earning a 
return for the months where the fund lacks returns. 
Fixed Rate – equivalent to the percent of capital invested in the fund without performance 
earning the interest in a savings account. 
Proxy Benchmark – for the fund without performance, the performance of the selected 
“benchmark” would be used until the fund in the portfolio has performance. For example, in 
Figure 32 the portfolio has a start date of January 2004 and Fund C has inception date of April 
2004. For the first quarter of 2004 Fund C is been backfilled with the performance of the HFRI 
Index, the proxy benchmark in this example. 
 
 
Figure 32: Using Backfill When There Is Nlo Monthly Data 
Por1follo 8"1Idor 
elo<I> Ml"'°"'" OW~ Upgqdtold 
~.3n P.Oltfcios 
~ Jf 
X 
AIIO<Mi"": Cu,_ 
I - I -. I ....... 15.od11!I 'Sl;•rt En~ U!Yllf'.ap• 11,U g~cin 
• U'l{1D/lPOl ~Ull 'l,QQQ•,QQQ 
• 01/.ll/lDO< ~•i •.aoa,ao• 
HIIIU~ 'W~l¢t~:I.Comp_ . o,v,~ ~•? '1,000,0QQ 
• ~D/1'95 Dl(il)2012 l ,D0~,0QQ 
._, ______________________________ ...._ _ _ No $o<k~II 
l'l«<!Rate 
Pr .... _.,,, 
S&PS011. hnd4D,. 
<lllen lloM Dpl Rwllor1t•toO!Nrl,..H · 
st.rt D.at•, Fbttd start Datil • Jan--2DM .. A,IIJ ■ lancc ft"tiqUtflOf! ~nually ,. 
EfldDltt: Jul), 
B J Ec,t ; ◄ 

---

### Page 41

  
                                                                                      www.evestment.com | 36 
 
Optimization 
In an effort to improve the portfolios performance there are different methodologies to assist the investor 
in determining the optimal allocations to funds in the portfolio. Some of the most commonly used 
methods are linear optimization, Markowitz Efficient Frontier and Black-Litterman. 
Linear optimization provides options in addition to the traditional tasks of maximizing return and 
minimizing volatility. For example, linear optimization can be used to allocate among the funds to 
minimize the drawdown or downside risk of the portfolio. Markowitz Efficient Frontier is an intuitive and 
easy to use model that is best fit when the funds historically have had a normal distribution and the 
funds are expected to perform similarly in the future.  However, linear optimization and Markowitz 
Efficient Frontier are models that rely on historical returns. When a fund’s future performance is believed 
to be different than the fund’s past performance the Black-Litterman optimization may be a good choice 
due to the relative and absolute views used to enter expected performance. 
All of these optimization methodologies allow for minimum and maximum allocation constraints that keep 
allocations within investment policy requirements. 
Linear Optimizer – as the name suggests, this optimization methodology is focused on a single 
performance or risk measurement to solve for the allocations to the underlying funds that maximizes the 
performance measurement or minimizes the risk measurement. 
Solvers calculate the selected statistics for the portfolio within the constraints set for the individual 
underlying assets. Then the allocations are changed and the selected statistic is calculated. Through 
multiple iterations an optimizer solves for the top portfolios for the selected criteria. 
Markowitz Efficient Frontier – a mean variance optimization methodology that for a selected level of 
risk determines the highest return or for a target return determines the lowest risk by allocating among 
the underlying funds. Inputs needed to create optimal portfolios are the expected returns, variances for 
all assets and covariance between all of the underlying funds in the portfolio. The inputs are calculated 
from the funds’ historical returns. As such the start and end dates used for the optimization are important 
factors in the outcome of the optimization. Depending on the investment horizon for the portfolio it may 
be appropriate to use a subset of the available data to determine the optimal allocations.  
Black-Litterman – like Markowitz Efficient Frontier, is a mean variance optimization methodology but 
allows the input of relative and/or absolute return assumptions. 
Market Capitalization of the asset classes in the portfolio is used to attempt to address over 
allocating to a single asset class. The Black-Litterman approach was originally used for global 
equities, bonds and currencies, where the market capitalization can fairly easily be determined. 
However, when using the approach with other asset classes the market capitalization might not 
be possible to ascertain. One suggestion for using Black-Litterman with a portfolio of hedge funds 
would be to use the fund’s AUM as a proxy for the market capitalization. 

---

### Page 42

  
                                                                                      www.evestment.com | 37 
 
Views allow assumptions about future expected performance to be used in lieu of the funds’ historical 
performance to determine the optimal allocation. The views can take two forms; relative and absolute. 
− The absolute view is a forecast of a funds future performance. Figure 33 
− A relative view is a statement that a fund or group of funds will outperform another fund or 
group of funds. Figure 34 
 
 
 
.. . ,1 
O llnmt11C"Grtad 
Figure 33: Black-Litterman Absolute View 
lr't\'estm«its- lti1um#fJW:S.: Canb!icwi 8.la<.t•Lfttffn"..w, 
Con,m,.,u M.,.. ,,._.. 
"" 
Figure 34: Black-Litterman. Relative View 
- .. -""~~& ~ 
Conitl>int> M¥.mc 
I~- ~.1 ... w_ ol_,o_m_• _~_ el_•d<-llll.,,,.. __ , ____________________________ --IY 
11\1 Mai"Ut Cap Yi twiN .ll'l!t I ~VIN I Rttutn. = 4.5.Q-% ;/ Ertablt 
CDdid1na11: ,.,_ 
.,I i.Mohrte~~"' 
lffw-..,.,... ~p~oms It-.~ 
FIIINII< Fond ~ 
., N.., V! ... I X J n,ndll fiW!dB 
~ 6lack•lilUfflll• Mad 
a Eff ..... t~ot,1,Mo 
~undC N nd C 
f1.11\d O fwldD 

---

### Page 43

  
                                                                                      www.evestment.com | 38 
 
Simulation 
Predicting Returns using Monte Carlo Simulation 
One method that can be used to predict returns is Monte Carlo simulation. Monte Carlo simulation is a 
method of generating thousands of series representing potential outcomes of possible returns, 
drawdowns, Sharpe ratios, standard deviations and other investments statistics of a specific investment 
or portfolio. The simulation calculates the uncertainty of a portfolio’s returns given its range of potential 
returns. Software that uses this simulation method can assess the probability of an individual achieving a 
retirement objective (and/or other financial objectives), given an investment portfolio’s specific asset 
allocation. 
Monte Carlo simulation using a bootstrapping technique allows for both skewness and kurtosis to be 
preserved. The bootstrapping technique involves resampling the actual data rather than assuming a 
normal distribution like standard deviation does. Monte Carlo simulations randomly construct a 
distribution of many possible returns for a portfolio over a specified time horizon. Thousands of possible 
results are calculated, and a probability profile is constructed for the various statistics. 
To see how this works, we can look at the stock market crash of 1987. From the period of January 1975 
to August 1987, the largest drawdown for the S&P 500 Index was 16.52%, and the average return was 
19.45%. Based on these numbers, few investors would have anticipated the crash of October 1987. 
However, using Monte Carlo simulation, we can see that there was the possibility of a market crash even 
in August 1987. Figure 35 shows the results of 10,000 Monte Carlo simulations on the S&P 500 Index, 
the "portfolio" in this example. Note that the 99th percentile indicates a possibility of a 28.83% 
drawdown. This percentile indicates that, however remote, there is the possibility of a significant 
drawdown, one which historical returns and standard deviations do not predict. 
Figure 35: Maximum Drawdown Monte Carlo Simulation for the S&P 500 Monthly Returns from January 1975 through August 1987 
Maximum ~ortfol!o ~ortfolio Difference B~nchm~rk Be_nchmark Difference 
Drawdown S1mulat1on Historical Simulation Historical 
Number Simulations 10,000 10,000 
Mean 12.24% 8.47% 
Median 11.13% 7.98% 
Standard Deviation 5.21% 3.95% 
Maximum 46.34% 16.52% 29.82% 35.54% 19.27% 16.27% 
Minimum 1.50% 16.52% (15.02%) 0.70% 19.27% (18.57%) 
99th Precentile 28.83% 16.52% 12.31% 21.05% 19.27% 1.77% 
95th Percentile 22.22% 16.52% 5.70% 16.08% 19.27% (3.1 9%) 
80th Percentile 19.21% 16.52% 2.69% 13.69% 19.27% (5.58%) 
75th Percentile 16.12% 16.52% (0.40%) 11.27% 19.27% (8.00%) 
70th Percentile 14.99% 16.52% (1.54%) 10.47% 19.27% (8.80%} 
65th Percentile 13.99% 16.52% (2.53%} 9.82% 19.27% (9.45%} 
60th Percentile 12.39% 16.52% (4.13%} 8.70% 19.27% (10.57%} 
50th Percentile 11.13% 16.52% (5.39%} 7.98% 19.27% (11.30%} 
40th Percentile 10.10% 16.52% (6.43%} 6.95% 19.27% (12.32%} 
30th Percentile 9.11% 16.52% (7.41%} 6.04% 19.27% (13.23%} 
25th Percentile 8.71% 16.52% (7.81%) 5.51% 19.27% (13.76%} 
20th Percentile 8.19% 16.52% (8.33%} 5.16% 19.27% (14.11%} 
10th Percentile 6.44% 16.52% (10.08%} 4.10% 19.27% (15.17%} 
5th Percentile 5.74% 16.52% (10.78%} 3.29% 19.27% (15.98%} 
1st Percentile 3.89% 16.52% (12.63%} 2.40% 19.27% (16.87%} 

---

### Page 44

  
                                                                                      www.evestment.com | 39 
 
Figure 36 shows the results of a Monte Carlo simulation that was run as of 6/30/2001.  Each bar 
represents the range of worst potential returns which have a 10% probability of occurring. As can be 
seen in the chart, from 1975 to 2001 the S&P never had a 
3 year to 10 year period that fell within the range.  However, as of June 2004 the S&P had experienced 
its worst performance in over a 25 year history. This example indicates that although there may be a 
discrete probability that an event might occur, it does not specify exactly at which time it will occur. 
 
 
 
 
Figure 36: 10% Confidence Level for the S&P 500 
1Yur 3Yur SYur 7Yea, 10Year 

---

### Page 45

  
                                                                                      www.evestment.com | 40 
 
VI. Fat Tail Analysis, Risk Budgeting, Factor Analysis & Stress Testing 
Fat Tail Analysis 
VaR (Value at Risk) - The highest possible loss over a certain period of time at a given confidence 
level. A 99% Value at Risk is interpreted as the level at which the losses of an asset or a portfolio will not 
be exceeded with a probability of 99%  (i.e. in 99 out of 100 cases the analyzed asset or portfolio  return  
will  be above the estimated  VaR value). Calculating VaR can be done using the historical fund data or 
parametrically fitting the data to a distribution and simulating the risk variables of this fund to create 
potential outcomes that did not occur in the past. The traditional way of calculating VaR parametrically 
utilizes the Normal distribution which only accounts for 2 moments, mean and standard deviation. It also 
assumes that the return distribution of risk variables is normally distributed despite ample empirical 
evidence against this assumption. Utilizing Normal VaR underestimates downside risk and can 
overestimate upside potential because the tails of these fund risk drivers are completely ignored. In 
addition, if the right tail is longer, the normal distribution may underestimate the upside potential and 
you run the risk of leaving money on the table. The Fat Tailed distribution helps you avoid this by 
accurately capturing both the left and right tails. To solve this problem, “Fat-tailed” VaR utilizes  the 
Skewed Student’s distribution which accounts for higher moments including skewness and degrees of 
freedom (tail fatness) allowing for a more accurate picture of tail activity and asymmetrical behavior.  
The Differences between Normal VaR, Modified VaR and “Fat-Tailed” VaR - In commercial 
products, VaR is widely used in combination with the normal distribution. In order to deal with the 
shortcomings of Normal VaR (as described above), Modified Value-at-Risk (mVaR) is often used. The 
calculation of mVaR is not tied to a distributional assumption. It can be viewed as a non-parametric 
estimator of the empirical VaR, employing the first four moments computed from the observed returns 
(Mean, Standard Deviation, Skewness, and Kurtosis). 
Some in the industry consider mVaR to be a “Fat-tailed” VaR. This statement is only true to the extent 
that it distinguishes mVaR from the Normal VaR methodology based on the normal distribution.  
However, mVaR is a non- parametric estimator and while it has some of its own merits, it is not much 
different than any other non-parametric estimator and has many deficiencies including: 
− It becomes less reliable for probabilities close to 0 or 1. That is, the deeper we go into 
the left or the right tail, the worse the approximation gets. In effect, VaR at high 
confidence levels get more inaccurate.  Basically, VaR at 99% cannot be reliably 
calculated. 
− It works well only for non-normal distributions which are “close” to the normal 
distribution and not for those which deviate significantly. As a result, it will not work well 
for distributions with high degree of skewness or fat tails. 
Therefore associating mVaR with the term “Fat-tailed” VaR is inaccurate.  Fat-tailed VaR is VaR based on 
a non-normal distributional assumption for risk factor returns. Recognizing that returns are fat-tailed and 
skewed one needs to explicitly assume that an appropriate non-normal distribution is necessary to model 
these properties. In this report, we use the Skewed Student’s t distribution to compute a true and more 
accurate fat-tailed VaR number. 
 

---

### Page 46

  
                                                                                      www.evestment.com | 41 
 
− ETL (Expected Tail Loss) – The average expected loss beyond VaR is also known as 
Conditional Value at Risk (CVaR) or Average Value at Risk (AVaR). It can be interpreted as the 
expected shortfall assuming VaR as a benchmark. ETL does not have the deficiencies of VaR as it 
is a true downside risk measure which can recognize diversification opportunities and has good 
optimality properties. ETL is a sub additive measure and therefore can be used to aggregate or 
decompose risk at the portfolio or strategy levels. This is why ETL is the risk measure used as the 
basis for risk budgeting. 
− ETR (Expected Tail Return) – ETR uses the same calculation as ETL, but refers to the positive 
side of the return distribution. 
− STARR Performance  – Similar to the Sharpe Ratio which is a standard deviation-based 
performance measure, but STARR (stable  tail-adjusted return ratio) uses the ETL in the 
denominator as a risk measure. STARR can be seen as a more effective indicator of risk-adjusted 
performance because it penalizes only for downside risk, while the standard deviation does not 
distinguish between upside and downside risk. 
− Rachev Ratio – The ratio of the ETR to the ETL. This ratio demonstrates the fund’s upside 
potential as measured by expected return in the right tail and expected loss in the left. This 
measure is similar to the Omega Ratio but is data adaptive because the confidence level is user 
defined (how far out into the tails to go). 
− Marginal Contribution to Risk (MCTR) / Marginal Contribution to Expected Tail Loss 
(MCETL) – These statistics show how much additional risk would be added to the portfolio if an 
additional 1% were to be invested in that specific manager. If the measure is positive for a 
portfolio fund, increasing the allocation by 1% to that fund would increase the portfolio's risk. If 
the measure is negative, increasing the allocation by 1% to that fund would decrease the 
portfolio's risk. Therefore, a negative MCTR/MCETL is a preferred characteristic for an 
investment.  MCTR uses Standard Deviation as the risk measure; MC ETL uses Expected Tail 
Loss. 
− Percentage Contribution to Risk (PCTR) / Percentage Contribution to Expected Tail 
Loss (PCETL) – These statistics give information about the fraction of total risk contributed by 
each of the funds in the portfolio. They are computed by multiplying the weight of the 
investment by their marginal contribution stat (defined above) and dividing the total by the 
appropriate risk measure. PCTR uses Standard Deviation as the risk measure; PC ETL uses 
Expected Tail Loss. Percentage contributions to risk sum up to 100%. 
− Skew – This statistic represents the shape of the fund’s distribution around the mean. A 
negative skewness measure indicates that the distribution is skewed to the left - (i.e. compared 
to the right tail, the left one is elongated.) The opposite conclusion is drawn in the case of 
positive values. 
− Excess Kurtosis – The measure of peak and tail fatness in the distribution. The tails of a 
probability distribution contain additional information about the extreme values a random variable 
can take. The value is the excess over the standard normal distribution, for which the kurtosis is 
3. Positive values signal more weight around the mean and fatter tails relative to the normal 
distribution. 

---

### Page 47

  
                                                                                      www.evestment.com | 42 
 
− Implied Return - This represents the return a fund must deliver in order to justify the amount 
of risk it contributes to the overall portfolio. In economic terms, the implied return can be seen as 
the hurdle rate of the fund given its risk profile. Implied return can either use volatility or ETL as 
its risk measure. When using ETL Implied Return is equal to the STARR optimal  portfolio  (tail  
risk-adjusted return optimal) multiplied by each fund’s marginal contribution to ETL

---

### Page 48

  
                                                                                      www.evestment.com | 43 
 
Risk Budgeting 
Risk budgeting involves looking at individual fund risk and return contributions and then reallocating to 
maximize portfolio performance. Risk budgeting is a powerful technique because it accounts not only for 
individual fund performance but also for interaction effects within the portfolio stemming from the 
dependency structure of the funds. 
Implied returns are the result of reverse engineering an optimal portfolio. The portfolio is optimal in th e 
mean-ETL sense, which signifies that the portfolio is using implied returns based on tail loss. Implied 
returns represent the return a fund must deliver in order to justify the amount of risk it contributes to the 
overall portfolio. In economic terms, the implied return can be seen as the hurdle rate of the fund given 
its risk profile. In the maximum STARR portfolio, implied returns and mean returns are equal. It follows 
that whenever there is a discrepancy between mean or expected returns and implied ret urns, there is 
room for improvement. The reallocation rule is: allocate to those funds for which mean return exceeds 
implied return; and decrease allocations to funds for which implied return exceeds mean return. 
Following these guidelines will improve the risk adjusted performance of your portfolio. 
Risk budgeting is a useful tool because it allows you to incorporate your knowledge of a fund’s liquidity 
and capacity in your portfolio thereby allowing you to make realistic allocation choices that fit into your 
current investment policy. These are just some considerations why risk budgeting may be more useful 
compared to the pure out of the box optimization approach. We usually recommend the use of 
optimization as a guideline and then reallocating the portfolio based on a well-constructed risk budgeting 
process. There are two ways to quickly select the funds with the best risk budgeting potential. In the 
data table there is a “Difference” column that shows the difference between Mean Return and Implied 
Return. The higher the number, the more this fund justifies its risk and can be considered a good 
candidate for increased allocation. Funds with negative “differences” may be considered redemption 
candidates. In the table below, Fund_16 would need to have a monthly mean return of 5.58 in order to 
justify its tail risk. However it only returns 3.47 per month (difference of -2.11), meaning that this fund 
may be considered for redemption or decreased allocation. On the other hand, Fund_78 only needs to 
have a monthly mean of 0.5 to justify its tail risk. However since it has a mean of 1.4 (difference of 0.9) 
you may consider an increased allocation to this investment. 
 
 
Portfolio Weight (%) PC to Return Mean Implied Difference 
Demo_Portfolio 
Fund_16 
Fund_78 
100 
3.58 
4.11 
27.8 
9.58 
2.58 
3.47 
1.4 
Return (Ell) 
5.58 
0.5 
-2.11 
0.9 

---

### Page 49

  
                                                                                      www.evestment.com | 44 
 
The second way to view this is by using the chart below. 
 
This chart provides a visual depiction of the mean return versus implied return concept. The diagonal line 
represents the STARR optimal portfolio (best tail risk-adjusted return ratio for the entire portfolio). Points 
above this line (i.e. point 14/ Fund_7) represent funds that have higher mean returns than implied 
returns meaning that their return to the portfolio more than justify the tail risk that they add. These 
funds provide you with good allocation opportunities. Points below the line are underperforming relative 
to the tail risk they are contributing. 
5.0 
J.S 
.. , 
J.O 
12.S • !> 
£: 
• ?? 
.. :!.O 
1..5 
2!!· 
LO 
o..s 
0.0 
• 31:l 
.oO.!S 
1,,0 / ·~ .... , 
/ 
·Z-0 
•U 0.0 .. 
• 1 
• i 
GI ,. 
L5 
"$ "'21 il • ) 
!OJ) 
ETL(be:111 
~ 
l,'ETI.J 
ll l'Vo 
l, Pali:illltd'I 
-~llll 
Rft1J 
-ru-ot.l~ 
~R.r•,U:t2 
t.~m 
7,1\n:l._-!O 
a fv,j_?9 
9,Rnl_77 
Fi,rd,JQ 
1 ~_113 
_'Ill 
• ' 111 
u 
i..19 
9 
7J 
~ 
_.,,, 
13 
08 
_,,. 
i.ffl 
~ 

---

### Page 50

  
                                                                                      www.evestment.com | 45 
 
Factor Analysis & Factor Contribution to Risk 
The purpose of factor analysis is to uncover the relationship between one dependent variable (typically a 
fund) and one or more explanatory variables (typically market or style indices) by using a statistical 
estimation method. The Stepwise regression method is a selection process that utilizes the Akaike 
Information Criterion (AIC for short) in order to select the factors that best explain the variance of each 
fund in your portfolio. Most stepwise regression methods in standard software packages either deploy a 
forward or a backward looking selection process. 
− Forward selection: Involves starting with no variables in the model, trying out the variables one 
by one and including them if they are 'statistically significant'. 
− Backward elimination: Involves starting with all candidate variables, testing them one by one for 
statistical significance, and deleting any that are not significant. 
It’s important to note that your system should utilize both, testing at each stage for variables to be 
included or excluded for the final model. The output of the calculation is always a set of coefficients 
which describes the linear dependency between the dependent and the explanatory variables.

---

### Page 51

  
                                                                                      www.evestment.com | 46 
 
The R² statistic measures the overall goodness of fit of the model. It shows you how much of the total 
variance of the fund can be accounted for by the factors. R² can take values between 0 and 1. R² value 
of 1 means that you have perfect fit of the model. There are no set rules for the range of R ² that would 
be indicative of a good model. In theory, hedge funds are supposed to be uncorrelated to the market in 
general, so finding a good model by using market factors should be impossible. However, this theory 
rarely holds since for most hedge funds, you will be able to find a set of factors that adequately captures 
the fund profile. In general, an R² above 0.7 is considered a good fit. An R² of 0.4 - 0.7 is an adequate fit 
and an R² below 0.4 is a poor one. The magnitude of the R² statistics varies across hedge fund 
strategies. An R² of 0.38 may be considered a poor fit for a directional strategy like long/short equity. But 
it can be a very reasonable fit for a relative strategy like fixed income arbitrage. Factor contribution to 
risk gives you insight into the breakdown of risk by its systematic and specific parts. It allows you to see 
the exposure of the portfolio to market factors and the contribution of those factors to the risk of the 
portfolio. The risk measure for this section is standard deviation. In other words, the provided 
information is about factor contribution to portfolio volatility. 
This section provides an analysis of the total risks of the portfolio broken down into two components: 
− Systematic Risk – the risk attributable to those factors to which the portfolio has exposure 
− Specific Risk – the risk which cannot be attributed to market factors. 
The included chart graphically shows this breakdown in percent of systematic and specific risks of the 
portfolio as well as the breakdown of the systematic portion of risk across all factors used in the model. 
The percentage of specific risk is represented by the blue bar on the chart. The red bars represent the 
percentage contribution to portfolio risk coming from each of the factors which form the systematic 
portion of risk. You can also view this in data format. 
0 
!; 
S& P GSC Crude 0 11 US:D 
S&P GSCI lndu 
MSO E:A fE USO 
Russell 3D00 
B rit:i~1 P P und Stl!rlins 
Euro 
Japtl'l e5' Ye n 
A siilll1 Ccnlll!!r libll! 5 
Cit:1ero up Wo rld Gove rnment Bond Index 
o oss,onr EM sovere1t1n & cr edit USO 
Eu rope:an Comoli!rtlblo! s 
Glob1 I EM C11!dit Eur/ M~ Afr lfi D 
GI obd EM Cr e dtt Latin Amerlc~ USO 
Glob~ H~h '11eld USO 
Morla ag• Mmt~r USO 
20•Yie:arTreasury Co n:stant Maturrtv Ri'tt 
3-Ye31Tte=r:.urycomt ant M.rturlty RW 
LI BOR 12Month Con 5bnt M atu,itv Rah EUR 
LI BOR 12Month Constwit Matutify Rate L6D 
L IBOA 0-ve r nle;ht R cf.e EUFI 
LIBOROllernl ~ht R::a USO 
MSO Sma I Minus L.re:c US 
IVISCI \lg Uf! M inu s Gra IMh U5 
CBOE Vi:Jla.llltv lnd eit a~ Difference 
Sp11c:ilic: Ri5k: 
~ 
0 
:;i 
0 
g 
-
I 
-
• 
■ 
-• 
I 
I 
I 
-• 
• 
~ 
~ 
!; 
0 
g ~ 
g; 
g 
0 
~ 

---

### Page 52

  
                                                                                      www.evestment.com | 47 
 
Stress Testing 
Portfolio value stress tests allow you to examine the effect of various scenarios on the value of your 
portfolio. You can use stress tests to investigate how the value of your portfolio would change under a 
hypothetical scenario or under a historical crisis that actually occurred in the past. For example, a single 
stress test will look at the performance of various indices during a specific period of time (i.e. during the 
market drawdown caused by the Lehman collapse of 2008). Based on the fund to factor relationship 
(beta) and the allocation (weight) of the fund in the portfolio, the stress test will determine how your 
portfolio would perform if this scenario were to occur again. A stress test report typically consists of 
several scenarios. 
 
We then break down the stress tests at the fund level to display the top ten funds based on the greatest 
negative impact. 
 
-2.DII 
Fund 1C Fund 2 Fund7 Fund A. 
fl'Jn.?llt lnVISlon Mlri: etD-t1v,11turn tv.9JAQCn :h 2001 ~ anCrt:I~ 
""' 
Sept - Oct Crash 2008 
Fundl Fund 2S Fund11 Fund1 4 Fun d l □ 
Sept · OctCr?d-. 
2008; 
Fund l6 
'nTC At'3::k 

---

### Page 53

  
                                                                                      www.evestment.com | 48 
 
VII. Measuring Private Equity Performance 
The old adage investment managers use is that past performance does not guarantee future results and 
you should not rely on past performance as a guarantee of future investment performance. 
The reality is that past performance is a critical component in the private equity investment decision 
making process. One of the first things an investor does when evaluating a private equity fund manager 
is to look back at their previous history – how have their funds performed and how did they create value? 
Usually this will begin with a review of the high-level performance numbers and extends into a more 
detailed analysis of their track record. And while a track record will not provide an investor with all the 
answers, it will provide the important questions they need to ask in further due diligence to gather data 
and make informed manager selection decisions. 
Using IRRs as a Key Measure of Performance 
The Internal Rate of Return (IRR), an annualized, money-weighted return, is one of the key return metric 
used within the private equity industry. Expressed as a percentage, it can seemingly be used to compare 
performance from manager to manager or fund to fund. In reality though, it is not always that 
straightforward and IRRs alone are not an accurate representation of performance. 
Take a look at the chart below with Managers A to D listed across the top. As you can see, if you just 
take IRR into account, Manager A is clearly the outperformer. Even when TVPI (the return of cost 
multiple) is applied you could still classify Manager A as a winner, but Manager B has produced an 
identical multiple – returning the same ratio of capital but at different times to produce the variance in 
IRR. 
 
Performance is even more accurately represented when Profit, Holding Period, and Cost are revealed. 
Gaining insight into this level of detail allows you to understand a manager’s performance better and 
assess the risk of investing with them depending on your goals – do you want a manager that is known 
for strategies that create slower returns but a larger monetary profit? You also will want to understand 
how likely it is for a manager to return capital in a shorter period of time than expected. Are you exposed 
to risk by being under allocated to private equity and so having to source new funds and managers to 
invest in? Or do you view this as the opportunity to put that money to work elsewhere? 
 
 
,c I D 
40°/o 32% 
1VPI 1.5 1.5 1.4 13, 
Profit 15 25 20 10 
Holding 5 s 2 5 
Cost 30 so 50 30 

---

### Page 54

  
                                                                                      www.evestment.com | 49 
 
Even more curiously, two identical IRR numbers will not always be derived in the same way. As you can 
see below, getting an early win (returning capital quickly) can help to boost the IRR. 
 
This highlights why when measuring private equity returns, high level numbers can be a good way to 
select those to investigate further, but other metrics must be taken into account. These high-level 
numbers also only tell you what the manager returned. The real goal of due diligence is to understand 
how they returned this and how repeatable this is. 
Predicting Repeatability of Success 
High-level performance numbers like IRR and TVPI tell you whether or not a manager has performed well 
in the past, but the real key is to understand how they generated that value in their portfolio companies 
and how this compares with their proposed strategy for the new fund.  
Valuation Bridges 
One of the commonly used methodologies is to calculate a Value Creation Bridge like the below graph 
shows. A visual representation of where value was added by a manager. This will allow you to quickly 
identify how factors such as currency impacted performance, and whether a manger focused on growing 
revenues or improving profits to warrant the sale cost. 
 
I E I F 
2005 -100 -100 
2006 75 
2007 
2008 2·00 81 
IRR 26% 26% 
lVPI 2.0x 1.16x 
Profit 100 56 
Val~o1,on Bndge <t di [!' X 
Oh oo, ·~ 
00, 
,., 
1 ;rr 
1 °' 
O&. 
O&, 
0.:.1 
Oh 
00, 
ENr, Ri, ... ES.TO.., 1 .... 0..... Vt. TO. 
= 
<)(-
°"'"''"" 
E,1 EQ.1~ 
!!::CJ.JC, 
"'"""' '·"" 
Rtci,ttM .,_,.,. ~ u-:t; ~ 
-,.._I 

---

### Page 55

  
                                                                                      www.evestment.com | 50 
 
Deal Analysis 
Understanding a manager’s likelihood of repeating success can also be gained by analyzing the spread of 
their portfolio companies performance – were there one or two deals that carried the rest of the 
portfolio? Or was performance outstanding in a certain sector or geography, with the rest lacking? 
Identifying any outliers and filtering them out of a track record is a useful way to understand how 
performance may have looked without them, and could look in the future if they followed the same 
strategy. 
 
Deal Attribution 
It is important to remember that the success of a private equity fund manager relies heavily on the 
individuals within the deal team. So it only makes sense that you would want to understand who was 
leading winning (and losing) deals and their role in the upcoming fund. 
 
 
TVPI v.s ln~led 
Paul Jooes III $1. lbn 
Kirk O'Shaunessy $,0.61ln 
BIii O!Maoolo $0. 5bn 
Elfzabeth Balcer :U. lbn 
Henryk Kania $0.1bn 
Joe Glasg1JW so. Sbn 
Bill Di Maggio so.Obn 
TVPI ¥ 
s 5-> 
so, 
!? 5 ~ 
2°'1: 
~ 
1 o, 
U)m 
0 5x 
00:. 
X 
)( 
)( 
X 
le 
X 
)( 
X 
le 
x X 
X 
)( 
)( 
)( 
~ 
:!01)-n 
)( 
X 
X 
I 0 ' 
■ Lead ■ Team 

---

### Page 56

  
                                                                                      www.evestment.com | 51 
 
This helps you identify questions to pose to the manager: If there is a star performer leading all the top 
deals, what risks do the fund and your capital incur if he leave? Getting to the bottom of these questions 
then helps you negotiate better when drafting investment terms for the Limited Partnership Agreement. 
Comparing Private Equity Returns to Public Markets 
High-level performance numbers like IRR and TVPI tell you whether or not a manager has performed well 
in the past, but the real key is to understand how they generated that value in their portfolio companies 
and how this compares with their proposed strategy for the new fund  
Public Market Equivalents (PME) covers a variety of methodologies for benchmarking private equity 
returns to listed public indices. 
 
PME has the advantage of benchmarking against a known quantity.  It can be used to measure the alpha 
generated over and above a market return or to assess the opportunity cost of investing in private equity.  
In its simplist form it can even be used to compare a private equity return figure with a more traditional 
time weighted return. PME can therefore be used as part of the asset allocation decision making process. 
The basic concept of PME analysis is to invest the private equity cashflows into and out of a listed index.  
There are a variety of different methodologies as to how best to achieve this. 
PME 
First proposed by Austin M. Long and Carig J. Nickels in 1996 (A Private Investment Benchmark).   They 
called it the ICM method (Index Comparison Method).  Also known as the Long Nickels PME or LN-PME. 
Creates a theoretical investment into the selected benchmark using the actual cash flows.  Each 
Contribution is invested in the index and each distribution is treated as a sale out of the index. 
This results in a theoretical NAV, which is substituted in place of the actual NAV in order to calculate an 
IRR. 
' 1~~·-- X f'!r X ~·,.,. X Pi!E Ao"" X ,,~4Clli::R 
...... .........._. l'IJo 
1.3x 17.3% 1 1 11 1 I I 
" " 
fl.I lla:.a 
... .... ... ... . ., .. ' "' . T ~ ... :od ~ ...... 
A-.O~A .• ,,., )( 
----
8.0% A •9.J¾ 8.0 % -9.J% 9.9% -1.9% us •·-
FfSE ~lL SIWIE P1 X 
·\r-, ... -v" 3.3% "'+ 1:).9% -1.0% ... +18.2', 6.9% ... +3.6'/2 1i.3.2 ...... ~~ 
X 
2.5% •,5, 14.~ -0.1% •+17 .J~, 5.7% ... +3.2'11 1i .. 29 ... ~".:I 
.~ 
~'<C SENCJII X 
6.3% ... ♦, 1.Q!, 0.6% A-+-16.6,~ 9.6% .. -3-3% 1.29 A•O;m,i·~ 
w;aElRCP£~1'1 )( 
U % -"'* lEi.1¾ -3,9% • -21.:>¾ 5 .. 2% • .... 4~1,; 1i.38 •-Clu!e,t,,~ 
FTSc ~lL Srt"Af 1\1 
Hi,M:; Sl;NC Pl 
I HoO.NG SE>.'G ~ 
A$0Elil'IOPEEPI 

---

### Page 57

  
                                                                                      www.evestment.com | 52 
 
The PME result is directly comparable to an IRR and so outperformance is measured against the IRR.  
Where the fund significantly outperforms the selected benchmark it can result in a short in the index and 
a negative value, which is not appropriate for calculating a PME result. 
Modified IRR 
The MIRR (Modified Internal Rate of Return) is a modification of the IRR with the intention of resolving 
the associated issues of the finance rate and re-investment rate. 
All contributions are discounted back to the initial cash flow date by the growth in the selected 
benchmark.  All distributions are discounted forward to the final cash flow date by the growth in the 
selected benchmark. 
The annualized performance can then be calculated using these two values as you would a Time 
Weighted Return (TWR). 
The MIRR is directly comparable to TWR of the selected benchmark over the same time period.  
PME Ratio 
First proposed by Steve Kaplan and Antoinette Schoar in 2005 (Private Equity Performance: Returns, 
Persistence and Capital Flows).  Also known as the Kaplan Schoar PME or KS-PME. 
Both the contributions and distributions are discounted back to the initial cash flow date by the growth in 
the selected benchmark. 
The resultant PV of all distributions is then divided the PV of all contributions. 
The PME Ratio is not directly comparable to an IRR or other measure.  Instead, if the ratio is in excess of 
1.0 then the fund is deemed to have outperformed the selected benchmark and where the ratio is below 
1.0 the fund is deemed to have underperformed the selected benchmark.  
PME+ 
First proposed by Thomas Kubr and Christophe Rouvinez at Capital Dynamics in 2003, it was patented in 
2010. In order to avoid the issue where PME results in a short position in the index and therefore a 
negative NAV, PME+ maintains the actual NAV and instead scales the distributions by a factor lambda. An 
IRR is then calculated on the revised cash flows. 
The PME result is directly comparable to an IRR and so outperformance is measured against the IRR  
Additional Tips 
It is important when using PME to take account of the comparability of the chosen index with the 
strategy being employed by the selected private equity manager.  Very few private equity firms target the 
scale of companies to be found in most listed indices.

---

### Page 58

  
                                                                                      www.evestment.com | 53 
 
Conclusion 
All investors who are required to select and monitor investment managers should develop a basic 
understanding of investment statistics. These tools will help make manager selection and monitoring 
easier and more productive. Of course, you can never neglect qualitative analysis, but you can and 
should use all of the quantitative tools at your disposal to narrow your list of investment candidates 
before you embark on the arduous process of due diligence. In addition, the quantitative tools will 
provide you with good insight that you can use in your qualitative interviews with managers, and when 
monitoring your investments. 

---

### Page 59

  
                                                                                      www.evestment.com | 54 
 
Appendix I: Key Investment Statistics 
We have categorized the key investment statistics according to absolute or relative return measures, risk-
adjusted return measures and risk measures. The explanations for each statistic are provided below.  
 
 
 
 
 
 
 
 
 
 
 
 
 
 
Table 5: Summary of Key Investment Statistics 
I. ABSOLUTE II. ABSOLUTE ill. ABSOLUTE IV. RELATIVE V. RELATIVE VI. RELATIVE VII. TAIL 
~ru~ m~ mK ~ru~ m~ mK mK 
MEASURES ADJUSTED MEASURES MEASU~S ADJUSTED MEASURES MEASU~S 
MEASURES MEASURES 
1. Monthly 1. Sharpe Ratio 1. Monthly 1. Up capture 1. Annualized 1. Beta 1. VaR 
Return Standard Ratio Alpha 
Deviation 
2. Average 2. calrnar Ratio 2. Gain Standard 2. Down capture 2. Treynor Ratio 2. Modified VaR 
Monthly Gain Deviation Ratio 
3. Average 3. Sterling Ratio 3. Loss Standard 3. Up Number 3. Jensen Alpha 3. Expected Tail 
Monthly Loss Deviation Ratio Loss (ETL) 
4. Compound 4. Sortino Ratio 4. Downside 4. Down Number 4. Info rrnatio n 4. Modified 
Monthly Deviation Ratio Ratio Expected Tail 
Return Loss 
5. Omeg-a 5. Skewness 5. Up Percentage 5. Jarque-Bera 
R-atio 
6. Kurtosis 6. Down 6. STARR Ratio 
Percentage 
R-atio 
7. Maximum 7. R-achev R-atio 
Drawdown 
8. Gain/Loss 
Ratio 

---

### Page 60

  
                                                                                      www.evestment.com | 55 
 
I. Absolute Return Measures 
1. Monthly Return (Arithmetic Mean): A simple average return (arithmetic mean) that is calculated 
by summing the returns for each period, and dividing the total by the number of periods. The simple 
average return does not consider the compounding effect of returns. 
 
2. Average Monthly Gain (Gain Mean): A simple average (arithmetic mean) of the periods with a 
gain. It is calculated by summing the returns for gain periods (returns 0), and dividing the total by the 
number of gain periods. 
 
3.  Average Monthly Loss (Loss Mean): A simple average (arithmetic mean) of the periods with a 
loss. It is calculated by summing the returns for loss periods (returns < 0), and dividing the total by the 
number of loss periods. 
 
 
 
 
 
 
Where N = Numb.er of periods 
Where Rtl = Return for period I 
N 
Average Retum = ( I: R1) ~ N 
Where N = Number of periods 
Whe.re R11 = Return for period I 
I'=~ 
Where 61 = R1 ( IF R1 ~ O ) or O ( IF R1 < D ) 
Nill = Number of periods that R11 ~ 0 
N 
Ave,rage Gaim = ( I: R1 ) 
1=1 
Whe.re N = Number of periods 
Where R11 = Return for period I 
N Ill 
Whe.re ~1 = D ( IF R1 ~ D ) or R11 ( IF R11 < 0 ) 
NL = Number of periods th at R1 < 0 
N 
Ave,rag1e, Loss = ( Z: L1 ) + NL 
1=1 

---

### Page 61

  
                                                                                      www.evestment.com | 56 
 
4.  Compound Monthly Return (Geometric): The monthly average return that assumes the same 
return every period that results in the equivalent compound growth rate from the actual return data. The 
geometric mean is the monthly average return that, if applied each period, would produce a final dollar 
amount equivalent to the actual final value- added monthly index (VAMI) for the fund’s return stream. 
(The VAMI reflects the growth of a hypothetical $1,000 in a given investment over time, with the index 
equal to $1,000 at inception.) 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
Where N = Number of periods 
Where Vami (0) = 1 000 
Gomp,ound MonlHlly FHJR = ( VamiN + Vami0 ) 111r41 - 1 

---

### Page 62

  
                                                                                      www.evestment.com | 57 
 
II. Absolute Risk-adjusted Return Measures 
1.  Sharpe Ratio: A measure of a fund’s return relative to its risk. The return (numerator) is defined as 
the fund’s incremental average return over the risk-free rate. The risk (denominator) is defined as the 
standard deviation of the fund’s returns. 
 
 
 
 
2.  Calmar Ratio: A return/risk ratio. The return (numerator) is defined as the compound annualized 
return over the last 3 years, and the risk (denominator) is defined as the maximum drawdown (in 
absolute terms) over the last 3 years. (If there is not 3 years of data, the available data is used.) 
Calmar Ratio = Compound Annualized ROR ¸ ABS (Maximum Drawdown) 
 
 
 
 
 
Where R1 = Return for period I 
Where MR,= Mean of return set R 
Where N = Number of Periods 
Where SD = Period Standard Deviation 
Where R AF = Period Risk Free Return 
lrAI 
MIR = ( L All ) ~ N 
1=1 
lrAI 
SD = ( 2: All - MR )2 .;. (N - 1) ) ½ 
1=1 
Annm,liz·ed Sharpe Ra,tio 
Anmualliz1ed Sharp,e = Monthly Sharpe x ( 12) ½ 
Anmualliz,ed Sharp,e'f< = Quarterly Sharpe x ( 4) ½ 
* Quarterly D a:ta 

---

### Page 63

  
                                                                                      www.evestment.com | 58 
 
3.  Sterling Ratio: A return/risk ratio. The return (numerator) is defined as the compound annualized 
return over the last 3 years, and the risk (denominator) is defined as the average yearly maximum 
drawdown over the last 3 years, less an arbitrary 10%. To calculate the average yearly drawdown, the 
latest 3-year returns (36 months) are divided into 3 separate 12-month periods, and the maximum 
drawdown is calculated for each.  These 3 drawdowns are then averaged to produce the average yearly 
maximum drawdown for the 3-year period. (If there are not 3 years of data, the available data is used.) 
 
 
4.  Sortino Ratio: A return/risk  ratio. The return (numerator) is defined as the incremental compound 
average period return  over a minimum  acceptable  return  (MAR), and the risk (denominator)  is defined  
as the downside  deviation below the MAR. 
 
 
5.  Omega: A relative measure of the likelihood of achieving a given return. It represents a ratio of the 
cumulative probability of an investment’s outcome above an investor’s defined return level (the threshold 
level), divided by the cumulative probability of an investment’s outcome below an investor’s threshold 
level. Omega considers all information readily available from the investment’s historical return data. The 
higher the omega value, the greater the probability that the given return will be met or exceede d. 
 
 
 
Where D1 = Maximum Drawdown for first 12 months 
Where D2 = Maximum Drawdown for next 12 months 
Where D3 = Maximum Drawdown for latest 12 months 
Average Drawdown = ( D1 + □ 2 + D3) + 3 
'St:er1iing Ratio = Compound Annualized A.OR+ ABS ( (Average Drawdown -10%)) 
Where A1 = A.eturn for period I 
Where N = Number of Periods 
Where RMAA = Period Minimum Acceptable Return 
Whe.re DDM1(R = Downside Deviation 
Where l.;1 = A11 - RMM ( IF A11 - RMAA < D ) or O ( IF Ai - AiM'AR ~ 0 ) 
N 
DDMM, = ( ( L ( 1.,1 )2 ..;. ( N ) ~ 
lb.1 
S.orthm Rati:o = ( Compound Period Return - RMAA.)..;. DDli\ll,R, 

---

### Page 64

  
                                                                                      www.evestment.com | 59 
 
III. Absolute Risk Measures 
1.  Monthly Standard Deviation: Measures the degree of variation of a fund’s returns around the 
fund’s mean (average) return for a 1-month period. The higher the volatility of the returns, the higher the 
standard deviation. The standard deviation is used as a measure of investment risk. 
 
 
 
2.  Gain Standard Deviation: Measures the fund’s average (mean) return only for the periods with a 
gain, and then measures the variation of only the winning periods around this gain mean. This statistic is 
similar to standard deviation, but only measures the volatility of upside performance. 
 
 
 
 
 
Where R1 = R.eturn f-or period I 
Where MR,= Mean of return set R 
Where N = Number of Periods 
N 
,Standard DevhrtJon = ( L ( R11 - M1t) 2 ~ (N - 1) ) ~ 
1=11 
An1111alized S,tandard oe,flia,tion 
AnrmaUz,ed Standard! Devia1iio1 = Monthly standard Deviation x ( 12 ) 1i 
Where N = Number of Periods 
Where R11 = Return for period I 
Where M6 = Gain Mean 
Where 61 = RI ( IF RI 3 D ) or O ( IF RI < 0 } 
Where GGII = RI - M 6 ( IF RII s: □ ) or □ ( IF RI < 0 ) 
N a = Number of periods that RI s O 
MR = ( L. RI ) -+, N 
1=1 
N 
Standard Deviation = ( I: ( R11 - M1t) 2 ~ (N - 1) ) ~ 
1!=1 

---

### Page 65

  
                                                                                      www.evestment.com | 60 
 
3.  Loss Standard Deviation: Measures the fund’s average (mean) return only for the periods with a 
loss, and then measures the variation of only the losing periods around this loss mean. This statistic is 
similar to standard deviation, but only measures the volatility of downside performance. 
 
4.  Downside Deviation: This measure is similar to the loss standard deviation except the downside 
deviation considers only returns that fall below a defined minimum  acceptable  return (MAR) rather than 
the arithmetic  mean. For example, if the MAR is 6%, the downside deviation would measure the 
variation of each period that falls below 6%. (The loss standard deviation, on the other hand, would take 
only losing periods, calculate an average return for the losing periods, and then measure the variation 
between each losing return and the losing return average). 
 
 
 
 
 
 
 
Where N = Number of Periods 
Where An = A.etu rn for period I 
Where M = Gain Mean G • 
Where G1 = R11 ( IF R1 3 O ) or O ( IF R1 < O ) 
Where GG11 = A1 - M 6 ( IF A11 s: □ ) or □ ( IF R1 < 0 ) 
N G = Number of periods that RI s O 
MR = er. A1 > --i,- N 
1=1 
N 
Standard Deviation = ( I: ( R11 - MR) 2 ~ (N - 1) ) ~ 
Where R1 = Return for period I 
Where N = Number of Periods 
1!=1 
Where AMM = Period Minimum Acceptable Return 
Where ~1 = A1 - RMAR ( IF A1 - AMAR < D ) or D ( IF A1 - A"'AR. ~ D ) 
1=1 
N 
lifownside D1eviatiion = ( ( E ( LI) 2 .;. N - ) ~ 
1=1 

---

### Page 66

  
                                                                                      www.evestment.com | 61 
 
5.  Semi Deviation: a measure of volatility in returns below the mean. It's similar to standard deviation, 
but it only looks at periods where the investment return was less than average return. 
 
 
 
6.  Skewness: This measure characterizes the degree of asymmetry of a distribution around its mean. 
Positive skewness indicates a distribution with an asymmetric tail extending toward more positive values. 
Negative skewness indicates a distribution with an asymmetric tail extending toward more negative 
values. 
 
Note: If there are fewer than three data points, or the sample standard deviation is zero, Skewness 
returns the N/A error value. 
 
 
 
 
Whern R1 = Re11turn for period II 
Whern N = Number of Pe11iods 
Whern Ml = Period Arithmetiic Mean 
Whern L = ~ - M (IF R - M < 0 \ m O ( IF R - M ~ 0 ) 
11 ''J II 1' 11 
NL = Number of periods that R11 - M < O 
N 
Semi Devia.tion = ( I: ( II.) 2 7 {NL - 1) ) ~ 
Where N "" Number of Periods 
Where R11 "" Return for period I 
Where M11 = Mean of return set R 
Where SD=- Period Standa.rd Deviation 
1=11 
Pl 
SD = o:: Rll- MIR) 2 + ( N - 1 ) )Y.' 
1=11 
1=1 
N 
Sk,ewness. "" (N-..- ((N-2)(N-2))) ( :E { R1 - MR).;. SD)) 3 

---

### Page 67

  
                                                                                      www.evestment.com | 62 
 
 
7.  Kurtosis: This measure characterizes the relative peakedness or flatness of a distribution  compared 
with the normal distribution. Positive kurtosis indicates a relatively peaked distribution. Negative kurtosis 
indicates a relatively flat distribution. 
 
Note: If there are fewer than four data points, or if the standard deviation of the sample equals zero, 
Kurtosis returns the N/A error value. 
Where N = Number of Periods 
Where A1 = A.etum for period I 
Where MR = Mean of return set R 
Where SD= Period Standard Deviation 
!I 
M A "" ( L Al ) ~ N 
1=1 
!I 
SD = ( L Al - M A ) 2 ~ ( N - 1 ) ) ~ 
1=1 
!I 
Kmi:osis ~ {(N(N+ 1) + ((N-1 )(N-2)(N-3))} (I: (R1 - MR) + SD))4} - (3(N-1 )2 + ((N-2){N-3))) 

---

### Page 68

  
                                                                                      www.evestment.com | 63 
 
8.  Maximum Drawdown: Measures the loss in any losing period during a fund’s investment record. It 
is defined as the percent retrenchment from a fund’s peak value to the fund’s valley value. The 
drawdown is in effect from the time the fund’s retrenchment begins until a new fund high is reached. The 
maximum drawdown encompasses both the period from the fund’s peak to the fund’s valley (length), and 
the time from the fund’s valley to a new fund high (recovery). It measures the largest percentage 
drawdown that has occurred in any fund’s data record. 
9.  Gain/Loss Ratio: Measures a fund’s average gain in a gain period divided by the fund’s average loss 
in a losing period. Periods can be monthly or quarterly depending on the data frequency. 
Gain/Loss Ratio = ABS (Average Gain in Gain Period ÷ Average Loss in Loss Period) 

---

### Page 69

  
                                                                                      www.evestment.com | 64 
 
IV. Relative Return Measures 
1.  Up Capture Ratio: Measures a fund’s compound return when the fund’s benchmark return 
increased, divided by the benchmark’s compound return when the benchmark return increased. The 
higher the value, the better. 
 
 
2.  Down Capture Ratio: Measures the fund’s compound return when the benchmark was down 
divided by the benchmark’s compound return when the benchmark was down. The smaller the value, the 
better. 
 
 
 
 
 
 
 
 
Where Ru = Return for period I 
Where RD11 = Benchmark Return f-or period I 
Where N = Number of Periods 
Where 1.,1 = A, (IF RD, ~O) or O (IF RD11 < 0) 
Where LD1 = R~ (IF A.D1 ~ 0) or O (IF RD1 < 0) 
1 = ((1+LJ X (1+!_,) X ... X (1 +Lr,)) -1 
1D = ((1+LDO) X (1 +LD1) X ... X (1 +LDN)) -1 
Up Capture = T ~ TD 
Where A11 = A.etu rn for period I 
Where R.D11 = Ben chm ark Return for period I 
Where N = Number of Periods 
Where ~ = R, (IF Rq, < 0) or O OF RD, ·~ 0) 
Where L □ , = R~ (IF A.D, < 0) or O (IF ADI ~ 0) 
T = ((1 +LJ X (1 +l,) X ... X (1 +1.,,1)) -1 
1D = ((1+LDO) X (1 +LD1) X ... X (1 +LDN)) -1 
Down Capture = T + TD 

---

### Page 70

  
                                                                                      www.evestment.com | 65 
 
3.  Up Number Ratio: Measures the number of periods that a fund’s return increased, when the 
benchmark return increased, divided by the number of periods that the benchmark increased. The larger 
the ratio, the better. 
 
Where Rd= R.etum for period I 
Where RD, = Benchmark Return for period I 
Where N = Number of Periods 
Where L1 = 1 (IF R1 ~ 0 AND RD, ~ 0) ELSE 0 
Where LD, = 1 (IF RD, ~ 0) ELSE 0 
Ill 
T = ( I, L,) 
1'=1 
IIA 
TD = CE LD1) 
1=1 
Up Nullilber Ratio = T ~ TD 

---

### Page 71

  
                                                                                      www.evestment.com | 66 
 
4.  Down Number Ratio: Measures the number of periods that a fund was down when the benchmark 
was down, divided by the number of periods that the benchmark was down. The smaller the ratio, the 
better. 
 
 
 
5.  Up Percentage Ratio (Proficiency Ratio): Measures the number of periods that a fund 
outperformed the benchmark when the benchmark increased, divided by the number of periods that the 
benchmark return increased. The larger the ratio, the better. This is a proficiency ratio. 
 
 
 
Where R11 = Return for period I 
Where RD 1 = Ben chm ark Return for period I 
Where N = Number of Periods 
Where ~1 = 1 (IF R1 < 0 AND RD11< 0) ELSE 0 
Where LD11 = 1 (IF R~ < 0) ELSE 0 
II 
T = ( L LIi) 
1=1 
II 
TD = (L LDI) 
1=1 
Down Numbe,r IRatiu = T .;. TD 
Where Ai, = Return for period I 
Where RD11 = Benchmark R.eturn for period I 
Where N = Number of Periods 
Where ~ = 1 (IF RI1 ~ RDI1 AND RDI ~ 0) ELSE 0 
Where LD1 = 1 (IF RD1 ~ 0) ELSE 0 
II 
T = ( L LI) 
1=1 
II 
TD = er LDI) 
1=1 
Up Perce111tage Ratio = T ~ TD 

---

### Page 72

  
                                                                                      www.evestment.com | 67 
 
6.  Down Percentage Ratio (Proficiency Ratio): Measures the number of periods that a fund 
outperformed the benchmark when the benchmark was down, divided by the number of periods that the 
benchmark was down. The larger the ratio, the better. This is also a proficiency ratio. 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
Where R1 = Return for period I 
Where RD1 = Benchmark: Return for period I 
Where N = Number of Periods 
Where ~1 = 1 (.IF RI ~ RDI AND RDI < 0) ELSE 0 
Where LDI = 1 (IF RD1 < 0) ELSE 0 
II 
T = ( :E L1) 
1=1 
II 
TD = CE LD11) 
1'=1 
Down Peroemtage, RatiI0, = T + TD 

---

### Page 73

  
                                                                                      www.evestment.com | 68 
 
V.  Relative Risk-adjusted Return Measures 
1.  Annualized Alpha: Measures the fund’s value added relative to a benchmark. It is the Y intercept of 
the regression line. 
 
 
 
*See Beta calculation on page 65. 
 
2.  Treynor Ratio: This measure is similar to the Sharpe ratio, but it uses beta as the volatility measure 
rather than standard deviation. The return (numerator) is defined as the incremental average return of a 
fund over the risk-free rate. The risk (denominator) is defined as a fund’s beta relative to a benchmark. 
The larger the ratio, the better. 
 
 
*See Beta calculation on page 65. 
 
 
 
 
 
 
Where M1R = The mean return of the independent variable 
Where MR□, = The me.an return of the dependent varia,ble 
Amn1alized Al[plha = ((1 + Alpha)12 - 1 
Amu1alized Alpha = ((1 + Alpha)4 - 1 
(Mo nth ly Data) 
(Quarterly □ a.ta) 
Where MR= Annualized Return of Investment 
Where ~AF = Annualized Risk Free Return 
lreymor Ratio = ( M R - R. RF) .. Beta* 

---

### Page 74

  
                                                                                      www.evestment.com | 69 
 
3.  Jensen Alpha: Measures the extent to which a fund has added value relative to a benchmark. The 
Jensen Alpha is equal to a fund’s average return in excess of the risk-free rate, minus the beta times the 
benchmark’s average return in excess of the risk-free rate. 
*See Beta calculation on page 65 
4.  Information Ratio: Measures the fund’s active premium divided by the fund’s tracking error. This 
measure relates the degree to which a fund has beaten the benchmark to the consistency by which the 
fund has beaten the benchmark. 
Information Ratio = Active Premium ÷ Tracking Error 
Active Premium = Investment’s annualized return - Benchmark’s annualized return 
 
 
 
 
Whern R1 = Benchmark Refom for period I 
Whern RD1 = Hetum for period I 
Whern MR = Mean of return set R (Benchmark) 
Whern MR'.0 = Mean of return se-t RD 
Whern N = Number of Periiodls 
Whern RRf = P,e ri od ms k Free Retu m 
MR = 1( L HI ) 7 N 
1=1 
MAD = ( L RD,1) 7 N 
1=1 
Jensen Al1pha = ( MAD - J\tF) - Bela* x ( MR - R;Ri=) 
Whern R1 = The retum of the independent varriable for periiod I 
Whern RD1 = The rnffiium of the dependent variablie for period Ill 
Whern N = Number of Periiodls 
N 
Trncking Error = ( (2: ( R,1 - RD1 ) 2 7 (N- 1) )½) x 12~ 
1=1 

---

### Page 75

  
                                                                                      www.evestment.com | 70 
 
VI. Relative Risk Measure 
1.  Beta: Represents the slope of the regression line. Beta measures a fund’s risk relative to the market 
as a whole (i.e. the “market” can be any index or investment). Beta describes the fund’s sensitivity to 
broad market movements. For example, for equities, the stock market is the independent variable and 
has a beta of 1. A fund with a beta of 0.5 will participate in broad market moves, but only half as mu ch 
as the market overall. 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
When:i R11 = The return of the im:lepefilrdlefilrt variable for period I 
Where RD1 = The return of the dependent variablie for period II 
Where MIR = Tlhe mean rieturn of the independent variiablle· 
Where MIR0 = The mean return of the dependerillt variable 
Where N = INuimber of Periods 
N r 
Beta = ( I: ( R1- MIR )(RD1 - M8J) 7 ( L i( R1- MR )r2 

---

### Page 76

  
                                                                                      www.evestment.com | 71 
 
VII. Tail Risk Measures 
1.  Value at Risk (Parametric VaR): The Value at Risk is the maximum loss that can be expected 
within a specified holding period with a specified confidence level. In the API the Value at Risk is 
expressed as a percentage loss. The VaR is returned  as a positive  percentage  even though  it 
represents  a loss. The VaR calculation  assumes a normal distribution of returns. 
 
2.  Modified Value at Risk: The Modified Value at Risk is calculated in the same manner as Value at 
Risk but doesn’t assume a normal distribution of returns. In contrast it “corrects” the Value at Risk using 
the calculated skewness and kurtosis of the distribution of returns. 
 
3.  Expected Tail Loss (ETL): The Expected Tail Loss is the average of returns that exceed VaR. Also 
known as CVaR 
 
4.  Modified Expected Tail Loss (ETL): The calculation of then Modified Expected Tail Loss is identical 
to the Expected Tail Loss with the exception that it uses the Modified Value at Risk. 
 
 
 
 
VaR = E(R) + Z/l 
Where{R) = the expected value of the returns, 
Where ,a = the variance of the returns. 
Where Zc = the Z-score at a given confidence level. We use the following Z-scores tor the four confidence levels: 
90.0% Z-score -1.28155 
95.0% Z-score -1.64485 
97.5% Z-score -1.95996 
99.0% Z-score -2.32635 
Where(R) = the expected value of the returns, 
Where ZG = the confidence level (i.e. 95%), and 
Where o - the variance of the returns. 
Where S = the skewness of then returns, and 
Where K = the kurtosis of returns. 

---

### Page 77

  
                                                                                      www.evestment.com | 72 
 
 
5.  Jarque-Bera: The Jarque-Bera test is a measure of the normality of a distribution of returns. It uses 
the calculated skewness and kurtosis of the distribution of returns. 
 
6.  STARR (Stable Tail Adjusted Return Ratio): Evaluation of risk adjusted performance  in an 
alternative to the Sharpe Ratio way, but  STARR takes into account the major drawback of the standard 
deviation as a risk measure, which penalizes not only for upside but for downside potential as well and 
employs the ETL of the asset returns for the performance adjustment. It is defined as: 
 
 
7.  Rachev Ratio: Rachev Ratio (R-ratio): Reward-to-risk measure and defined as the ratio between the 
ETL of the opposite of the excess return at a given confidence level 1- α and the ETL of the excess return 
at another confidence level 1- β . That is: 
 
 
Rachev Ratio is the Expected Tail Return (ETR) divided by Expected tail loss (ETL). ETL is the average of 
the returns that exceed your VaR number in the left tail, the ETR is the average of the 5% of returns in 
the right tail at the 95% confidence level. 
 
 
 
 
 
Jarque-Bera. = n[S2 .+ (K - 3)2/4]/6 
Where n = the number of returns, 
Where S - 1he skewness of ·the returns 
Where K = ·the kurtosis of the returns. 
STARR = E(r1P - r1) 
ETI,_ a:(rp} 
R - Ratio = ETI,_ a {~rl'sk-troo I oenchmar\k - r p:iliilllillHasset) 
E 111-p (r J)lrtfollo I asset - r n3klrE!a I tninctlmatk) 

---

### Page 78

  
                                                                                      www.evestment.com | 73 
 
VIII. Holdings Analysis Measures 
1. Active Share  
Active Share is one-half of the sum of the absolute values of differences between the benchmark 
and portfolio for all positions, expressed as an integer between 0 and 100. Zero Active Share 
represents a portfolio identical to the benchmark, while an Active Share of 100 indicates that the 
portfolio and benchmark have no positions in common. The measure is calculated at a point in 
time, likely on quarter-end positions, and is often presented as a three-year moving average.  
 
Where wfund,i and  windex,i are the portfolio weights of asset i in the fund and in the index, and the 
sum is taken over the universe of all assets.  
2. Overlap:  
Overlap between two products is calculated by summing the minimum weight in each assetfor 
the two portfolios. It is independent of AUM or leverage. Overlap seeks to show the degree to 
which two portfolios are different based on their weighted holdings. It assumes that both 
portfolios are held at equal weight: Portfolio A = 50%, Portfolio B = 50%. 
3. Peer Share 
Peer Share is similar to Active Share except that instead of an index, Peer Share measures the 
percentage or equity holdings in a portfolio that differ from the eVestment Peer Alpha universe 
constituents. eVestment has assembled 49 peer universes, constructed on investment style 
factors such as capitalization, quality and sector emphasis. Peer groups are reconstituted 
quarterly. It is calculated by summing the absolute difference of the weight of each holding in the 
portfolio versus the eVestment Peer Alpha universe and dividing by two. 
 
 
 
 
 
 
 
 
Active Share = 1 
2 
N 
~ I Wfund,i - W index,i I 
i=1 

---

### Page 79

  
                                                                                      www.evestment.com | 74 
 
4. Active Share Efficiency 
Active Share Efficiency is the ratio of a portfolio’s excess return for a given quarterly period to its 
active share at the end of the period. 
 
 
where Re is excess return (expressed as an integer) and AS is Active Share (measured as a 
decimal). Similar to other measures, it can be viewed as an average excess return over multiple 
time periods (average rolling periods) as to limit endpoint sensitivity. In that case, the formula 
would change slightly, (where n equals number of periods) to include average excess return 
divided by average active share: 
 
 
5. Peer Share Efficiency 
Peer Share Efficiency is an extension of Active Share Efficiency to eVestment’s Peer Share 
statistic. Peer Share measures the Active Share of equity strategies against their eVestment Peer 
Alpha universe. eVestment has assembled 49 peer universes, constructed on investment style 
factors such as capitalization, quality, and sector emphasis. Peer groups are reconstituted 
quarterly. Peer Share Efficiency, then, compares a given manager’s Active Share Efficiency to the 
average Active Share Efficiency for the specified peer group.  
 
 
 
 
 
 
 
 
Re 
Active Share Efficiency = 
AS 
n 
( 
LRei 
) i=1 
n 
Active Share Efficiency = 
n 
( 
rAsi 
) 
i=1 
n 

---

### Page 80

  
                                                                                      www.evestment.com | 75 
 
IX.  Private Equity Performance Calculations 
1. Internal Rate of Return  
The Internal Rate of Return (IRR) is the discount rate that makes the net present value (NPV) of 
all future cash flows (inflows and outflows) to and from a particular investment equal zero. 
 
Where: 
NPV is the net present value. 
I is the income stream amount (cash flows) for each year or period. 
N is the number of years or periods, starting with 0, which is the current period or year. 
R is the discount rate/IRR you are trying to calculate (assumed to be constant in the future). 
2. Money Multiples  
PIC 
Paid-in Capital to Committed Capital shows you how much of the investors committed capital has 
been drawn. 
Paid-in Capital to Committed Capital (PIC) = Paid-in capital (cumulative contributions)/committed 
capital. 
DPI 
DPI Shows you how much of the invested capital was actually returned to investors. Early in the 
fund life cycle it tends to be zero until cash is distributed. When it is greater than 1, the fund has 
broken even. Calculated by taking the sum of all distributions divided by Total Invested.  Also 
known as the Cash on Cash (CoC) multiple. 
Distributions to Paid-in Capital (DPI) = Distributions/Paid-in Capital 
RVPI 
Calculated by taking the residual valuation divided by Total Invested. 
Residual Value to Paid-in Capital (RVPI) = NAV (net asset value)/Paid-in capital 
 
 
 
.N l 
' n = D NPV = ~ (1 +r)n 
n=o 

---

### Page 81

  
                                                                                      www.evestment.com | 76 
 
TVPI 
Calculated by taking the sum of all Distributions and Valuation divided by Total Invested. TVPI is 
a combination of DPI and RVPI. 
Total value to paid-in capital (TVPI) = (NAV+Distributions)/Paid-in Capital 
 
3. Additional Private Equity Metrics 
Enterprise Value (EV) 
The enterprise value of a portfolio company 
EV = Equity plus net debt 
Debt Capitalization 
The percentage of Enterprise Value represented by Debt. 
Debt Capitalization = debt/(equity + debt) 
Equity Capitalization 
The percentage of Enterprise Value represented by Equity. 
Entry Capitalization = equity/(equity + debt) 
Leverage 
The ratio of Debt to Equity. 
Leverage = Debt/Equity 
Total Value 
The sum of amounts returned from a deal (distributions) and valuation of the deal as at the track 
record date. 
Total Value = Distributions + Valuation 
EBITDA 
A definition of profit based on Earnings Before Interest, Tax, Depreciation and Amortization.  
EBITDA Margin 
A portfolio company’s profit margin. Expressed as a percentage 
EBITDA Margin = EBITDA/Revenue 
 

---

### Page 82

  
                                                                                      www.evestment.com | 77 
 
Multiple 
What multiple of EBITDA, the EV of a business represents. 
Multiple = (Equity + Debt) / EBITDA 
Debt Multiple 
What multiple of EBITDA, the debt of a business represents. 
= Debt/EBITDA 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 

---

### Page 83

  
                                                                                      www.evestment.com | 78 
 
About eVestment 
eVestment provides a flexible suite of easy-to-use, cloud-based solutions to help the institutional 
investing community identify and capitalize on global investment trends, better select and monitor 
investment managers and more successfully enable asset managers to market their funds worldwide. 
With the largest, most comprehensive global database of traditional and alternative strategies, delivered 
through leading-edge technology and backed by fantastic client service, eVestment helps its clients be 
more strategic, efficient and informed. 

---

