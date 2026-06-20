Technical Specification Document: Real-Time Tracking, Live Evaluation, and Interactive Dashboard Architecture for the World Cup 2026 Goal Prediction ChallengeContext, Motivation, and Operational ParadigmPredictive sports competitions on platforms like Kaggle and Zindi generate substantial engagement during live tournaments [cite: user prompt, 19]. However, participants often encounter a significant bottleneck once their predictive models are locked and the actual games begin [cite: user prompt, 17]. This technical friction was prominently addressed during the Kaggle March Machine Learning Mania 2026 event by a custom-built Telegram monitoring bot [cite: user prompt]. That system automated the manual overhead of tracking daily match progressions, calculating Brier scores on the fly, and dynamically projecting final bracket outcomes against a frozen submission model [cite: user prompt].A similar structural challenge exists for the Zindi World Cup 2026 Goal Prediction Challenge. In this competition, models were developed using the historical Fjelstul World Cup Database—covering tournaments through 2022—and were locked on June 19, 2026, just as the live tournament commenced. Because this is a strictly closed-data challenge, any external information generated during the 2026 tournament, such as team lineups, squads, or live odds, was prohibited in the submitted models. This separation between historical model training and the live tournament creates a compelling use case for a real-time evaluation tracking system.The actual tournament runs from June 11 to July 19, 2026. Tracking predictions across the expanded 48-team, 12-group, and 104-match format is highly complex, especially when evaluating multi-class tournament stages alongside cumulative team goals. Manual evaluation is difficult because team goal tallies must be tracked dynamically, and knockout stage qualifications must be verified programmatically.To solve this, the proposed architecture provides automated live metric updates, comparative user rankings, and visualized progress charts through a dual-channel framework [cite: user prompt, 42]. This design incorporates a native Telegram bot for push notifications alongside an interactive web-based dashboard [cite: user prompt]. The web interface serves as a companion for visitors who do not use Telegram, using client-side storage to preserve privacy and reduce system overhead [cite: user prompt, 42].Unified Core Engine and Multi-Channel ArchitectureThe system uses a decoupled, event-driven architecture designed to support a stateless REST API, a webhook-driven Telegram interface, and a lightweight Progressive Web App [cite: user prompt, 42]. This design ensures that the system can process live score feeds and scale smoothly during peak match windows.                                  +-------------------+
                                  | Live Data Feeds   |
                                  | (API-Football,    |
                                  |  ESPN Scoreboard) |
                                  +---------+---------+
                                            |
                                            v
+------------------+              +---------+---------+              +------------------+
|                  |              |                   |              |                  |
|   Telegram Bot   |<------------>|  Platform Core    |<------------>|  Web Companion   |
|   Interface      |  HTTPS/WSS   |  Engine & Backend |  HTTPS/WSS   |  PWA Front-End   |
|                  |              |                   |              |                  |
+------------------+              +---------+---------+              +------------------+
                                            |
                                            v
                                  +---------+---------+
                                  | Relational DB     |
                                  | & Redis Cache     |
                                  +-------------------+
The core engine handles file validation, mathematical scoring, simulation projections, and data collection from external sports APIs. The Telegram Bot serves as an active interaction channel, providing direct messaging, interactive menus, and push notifications when goals are scored [cite: user prompt, 42].The Web Companion operates as a static, single-page progressive web application. It allows users to upload their prediction CSVs without creating an account [cite: user prompt, 41]. The application parses the file locally and stores it in browser-level localStorage or IndexedDB.When the user opens the dashboard, the application sends their prediction vectors to the core API [cite: user prompt, 21]. The backend evaluates these vectors against the live tournament state and returns real-time metrics and dynamic bracket structures [cite: user prompt, 38]. This client-side approach reduces database writes and ensures that visitors without Telegram can access identical real-time analysis tools [cite: user prompt, 42].Tabular Data Ingestion and Validation EngineThe ingestion engine processes user-uploaded prediction CSV files [cite: user prompt, 4]. It validates file formatting, ensures clean database entries, and translates the generic competition rows into real-world national teams.CSV Structural SpecificationsColumn HeaderData TypeValidation ConstraintsDomain DefinitionidAlphanumeric StringMust match the exact team identifier structure defined in Test.csv.Represents the unique hash linking the prediction row to a specific national team.total_goalsFloatMust be a non-negative number ($\ge 0$). Outlier warnings trigger for values above 35.Represents the predicted cumulative goals scored by the country during the tournament.TargetEnumerated StringMust strictly match one of the seven valid categorical tournament stages.Represents the predicted exit stage for the specified country.The system rejects any uploaded files containing duplicate team IDs, missing rows, or invalid stage labels.Valid Tournament Stage MappingEnumerated TargetStage LabelStage KeyValidation CriteriagroupGroup StagegroupTeam is eliminated during the round-robin group phase.roundof32Round of 32roundof32Team qualifies for the knockout phase but exits in the round of 32.roundof16Round of 16roundof16Team qualifies for the knockout phase but exits in the round of 16.qfQuarter-finalsqfTeam is eliminated in the quarter-final match.sfSemi-finalssfTeam is eliminated in the semi-final matches.runnerupRunner-uprunnerupTeam advances to the final but loses the championship game.championChampionchampionTeam wins the final match of the tournament.Real-Time Match Data Ingestion PipelineTo compute live score shifts and update user performance brackets, the ingestion pipeline queries external sports data providers [cite: user prompt, 44]. The pipeline integrates several API sources to balance data reliability, cost, and rate limits.Live Data Feed SourcesData SourceTargeted EndpointAccess CostRate LimitsReal-Time LatencyCaptured FieldsAPI-FootballGET /v3/fixtures?league=1&season=2026[cite: 9]Free tier100 requests / dayUnder 60 secondsMatch events, official goalscorers, and confirmed lineups.ESPN Scoreboard APIGET /soccer/fifa.world/scoreboard[cite: 9, 10]KeylessNo official rate limitsImmediate live feedScore progression, live cards, and match status flags.Football-Data.orgGET /v4/competitions/WC/matches[cite: 9, 14]Free tier10 requests / minute5-minute delayVerified final scorelines and group tables.Mundial '26 Open APIGET /api/v1/matches[cite: 15]100% FreeNoneUnder 60 secondsMultilingual metadata, live goals, and standings.The data acquisition engine runs an active polling scheduler that adjusts its frequency based on the tournament calendar:Dormant State: When no games are active, the pipeline runs once every 6 hours to check for schedule adjustments or venue updates.Active Window State: Starting 30 minutes before kickoff, the scheduler polls every 5 minutes to confirm lineups.In-Play State: During matches, the pipeline query rate increases to once every 60 seconds, using the ESPN keyless feed to fetch goal events and scorer updates.Finalization State: Once a game is completed, the engine cross-references the result across at least two sources before committing the final scores and updating the database.Handling Penalty Shootouts: Goals scored during penalty shootouts are excluded from the target calculation. The ingestion engine filters out shootout goals by analyzing match event flags (goalType vs. penaltyShootout) before updating the database.Dynamic Live Metrics and Statistical Evaluation EngineThe evaluation engine calculates model performance using the competition's dual-metric framework: a Goals Prediction task evaluated by Root Mean Squared Error (RMSE) and a Tournament Stage Prediction task evaluated by F1-Score.               +--------------------------------------+
               |    Multi-Metric Evaluation Engine    |
               +------------------+-------------------+
                                  |
         +------------------------+------------------------+
         |                                                 |
         v                                                 v
+--------+--------+                               +--------+--------+
|  Goals (60%)    |                               |  Stage (40%)    |
|  RMSE Metric    |                               |  F1-Score       |
+--------+--------+                               +--------+--------+
         |                                                 |
         |  g_i = actual goals                             |  y_i = actual stage
         |  \hat{g}_i = predicted goals                    |  \hat{y}_i = predicted stage
         |                                                 |
         +------------------------+------------------------+
                                  |
                                  v
              +-------------------+-------------------+
              |  Weighted Combination Formulation     |
              |  (Stochastic Projections for Live)    |
              +-------------------+-------------------+
                                  |
                                  v
                      +-----------+-----------+
                      | Global Platform Rank  |
                      +-----------------------+
Mathematical FormulationsGoals Prediction (60% Metric Weight)The goals metric uses Root Mean Squared Error to measure the error between predicted and actual goal tallies across all forty-eight teams.$$\text{RMSE} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} (g_i - \hat{g}_i)^2}$$Where:$N$ is the number of evaluated national teams ($48$ in the 2026 format).$g_i$ represents the verified actual cumulative goals scored by national team $i$ during the tournament (excluding penalty shootouts).$\hat{g}_i$ represents the user's predicted goal count for team $i$.Tournament Stage Prediction (40% Metric Weight)The tournament stage metric evaluates predictions using a macro-averaged F1-Score across the seven categorical stages.$$\text{Precision}_s = \frac{\text{TP}_s}{\text{TP}_s + \text{FP}_s}, \quad \text{Recall}_s = \frac{\text{TP}_s}{\text{TP}_s + \text{FN}_s}$$$$\text{F1}_s = \frac{2 \times \text{Precision}_s \times \text{Recall}_s}{\text{Precision}_s + \text{Recall}_s}$$$$\text{Macro F1} = \frac{1}{S} \sum_{s=1}^{S} \text{F1}_s$$Where:$S$ is the number of categorical stage classes ($7$).$\text{TP}_s$, $\text{FP}_s$, and $\text{FN}_s$ represent the true positives, false positives, and false negatives calculated for stage class $s$.Comprehensive Score CompositionThe final leaderboard score is calculated as a weighted mean of the normalised RMSE and Macro F1-Score:$$\text{Overall Score} = 0.60 \times \text{Normalised RMSE} + 0.40 \times \text{Macro F1}$$Where:$\text{Normalised RMSE}$ standardizes raw error calculations against user baseline distributions to prevent early-tournament compression.$$\text{Normalised RMSE} = 1 - \left( \frac{\text{RMSE}_{user} - \text{RMSE}_{min}}{\text{RMSE}_{max} - \text{RMSE}_{min}} \right)$$Real-Time Incomplete Metric HandlingCalculating actual RMSE and F1-scores presents a logical challenge early in the tournament: actual goal tallies are incomplete, and most team exit stages are unresolved. To address this, the evaluation engine runs calculations through two distinct analytical pipelines:Progressive Current-State Baseline:
Actual goals ($g_i$) are set to currently scored tallies. Unresolved stages are designated as the team's current active round. For example, if team $A$ is active in the Group Stage, its actual stage target is marked as group. If team $A$ advances to the Round of 32, its target shifts to roundof32. This baseline provides a real-time trailing metric [cite: user prompt, 17].Stochastic Monte Carlo Projection:
During active matches, a simulator runs $10,000$ simulated tournaments from the current match state to project final metric outcomes. The simulator determines the probability of win/draw/loss outcomes for all remaining fixtures using Poisson distributions based on team Elo ratings and current expected goals ($\text{xG}$).$$\text{Probability}(k \text{ goals scored by } T_x) = \frac{\lambda^k e^{-\lambda}}{k!}$$Where $\lambda$ represents the baseline team strength parameter updated live. This projection generates expected probability distributions for goals scored and stage exit rounds, producing expected RMSE, expected F1-score, and a projected final leaderboard rank [cite: user prompt, 38, 41].Inter-User Comparative Analytics and Consensus GenerationThe platform aggregates user predictions to compute relative percentile standings and track cohort metrics across the user base [cite: user prompt]. These calculations help contextualize how an individual's predictions compare to the broader group [cite: user prompt].User Cohort Metrics and Aggregate ForecastsCalculated VariableMathematical EngineApplicationVisual DisplayTeam Goal DensityProbability density function of user-predicted goals per team.Highlights where an individual's predictions diverge from the user average [cite: user prompt].Frequency histogram on web dashboard [cite: user prompt, 46].Stage Progression ConsensusFrequency of predicted exit targets for each country.Measures collective user sentiment regarding how far each team will advance [cite: user prompt, 21].Percentage bar chart per team [cite: user prompt, 46].Common Scorer IndexesInverse-frequency weighting applied to correct predictions.Awards higher weights to unique, correct predictions over common consensus picks [cite: user prompt, 39].Custom "Divergence Score" [cite: user prompt].Brier Consensus IndexGroup Brier score calculated for each match [cite: user prompt].Evaluates how the user cohort performs collectively against real outcomes [cite: user prompt].Running group chart [cite: user prompt, 46].By analyzing these variables, the platform can rank users globally and calculate a "Surprise Index" that measures how much an individual's predictions differ from the consensus baseline [cite: user prompt, 41].Personalized Event Notification and Push ArchitectureReal-time notifications keep users updated on game events and metric adjustments [cite: user prompt, 42]. The alert system uses webhooks to process live match feeds, calculate metric shifts, and dispatch updates to the correct interface channel [cite: user prompt].+-----------------------------------------------------------------------------------------+
|                               NOTIFICATION ENGINE WORKFLOW                              |
+-----------------------------------------------------------------------------------------+
|                                                                                         |
|  [ Live Match Data Feed ] ---> ( Goal Scored / Match Finalized )                        |
|                                             |                                           |
|                                             v                                           |
|                                ( Compute Metric Deltas )                                |
|                                             |                                           |
|                      +----------------------+----------------------+                    |
|                      |                                             |                    |
|                      v                                             v                    |
|         ( User RMSE Impact: ΔRMSE )                   ( User F1 Impact: ΔF1 )           |
|                      |                                             |                    |
|                      +----------------------+----------------------+                    |
|                                             |                                           |
|                                             v                                           |
|                              ( Build Messaging Payloads )                               |
|                                             |                                           |
|                      +----------------------+----------------------+                    |
|                      |                                             |                    |
|                      v                                             v                    |
|         [ Telegram Bot Dispatcher ]                    [ Web Push Service W3C ]         |
|                      |                                             |                    |
|                      v                                             v                    |
|         ( Deliver Direct Messages )                   ( Deliver Browser Alerts )        |
|                                                                                         |
+-----------------------------------------------------------------------------------------+
Notification Trigger Logic and Payload ConstructionWhen a goal is scored or a match concludes, the platform updates its internal tournament tables and recalculates metrics [cite: user prompt, 40]. The notification engine then constructs a personalized payload for each affected user [cite: user prompt].Example Telegram Goal Scored Payload⚽ GOAL IN PROGRESS: Netherlands 1 - 0 Sweden (9')
Scorer: Brian Brobbey

Your Predictions Impact:
* Predicted goals for Netherlands: 4.00
* Real-world goals: 2.00
* Dynamic RMSE Shift: Changed from 1.62 to 1.58 (+0.04 accuracy gain)

Cohort Comparison:
* You predicted Netherlands to score above the user average of 2.12 goals [cite: user prompt].
Example Telegram Match Finished Payload🏁 MATCH FINALIZED: Canada 6 - 0 Qatar

Progression Stage Status:
* Canada has qualified for the Round of 32 [cite: 7, 8]
* Qatar has been eliminated in the Group Stage

Your Predictions Impact:
* Your prediction for Qatar (group): CORRECT!
* Your prediction for Canada (qf): Active
* Dynamic Macro F1 Shift: Changed from 0.52 to 0.58 (+0.06 accuracy gain)

Cohort Comparison:
* Only 12% of bot users predicted Canada to win by more than 4 goals [cite: user prompt].
Visual Bracket Synthesis and Dynamic Flow GenerationTo provide a visual alternative to standard sports schedules, the platform includes a rendering system that generates dynamic bracket images [cite: user prompt, 42]. This rendering engine produces customizable tournament flowcharts across both user interfaces [cite: user prompt, 42].Bracket Rendering SpecificationsSVG Template Architecture:
The system uses a static SVG skeleton to represent the 104 matches and progression steps of the 48-team, 12-group format. The bracket maps group tables, wildcards, and knockout stages dynamically.Visual Data Mapping:
The rendering engine uses distinct visual identifiers to display prediction outcomes on the SVG layout [cite: user prompt, 42]:Green Highlighting: Indicates correct stage predictions [cite: user prompt, 21].Red Highlighting: Indicates incorrect stage predictions, displaying the actual team's progress alongside the user's predicted team [cite: user prompt, 21].Grey Traces: Indicates future projected progressions.Dynamic Match Cards: Hover elements on the web platform display goal differentials and prediction error statistics.Output Optimization:
On the Web Companion, the SVG is injected directly into the DOM to support smooth zooming, tooltips, and interactive pans. For the Telegram interface, the backend converts the customized SVG into a high-resolution PNG image before transmission [cite: user prompt].Persistence Layer Database SchemaThe core backend uses a structured relational database schema configured to run on PostgreSQL. This layout supports live score writes during matches while quickly serving user metric queries.SQL-- Core Users Table: Supports Telegram sessions and anonymous Web identifiers
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_chat_id BIGINT UNIQUE,
    web_session_id VARCHAR(255) UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Submissions Index: Links to uploaded prediction files
CREATE TABLE submissions (
    submission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    file_hash VARCHAR(64) NOT NULL,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Teams Core Table: Tracks live scores and tournament stage status
CREATE TABLE teams_state (
    team_id VARCHAR(50) PRIMARY KEY, -- Logical code mapped from Test.csv
    team_name VARCHAR(100) NOT NULL, -- Display name of the country
    actual_goals INTEGER DEFAULT 0,  -- Total goals, excluding shootouts
    current_stage VARCHAR(50) DEFAULT 'group' -- Current round or final exit stage
);

-- User Predictions Table: Stores parsed predictions
CREATE TABLE predictions (
    prediction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id UUID REFERENCES submissions(submission_id) ON DELETE CASCADE,
    team_id VARCHAR(50) REFERENCES teams_state(team_id),
    predicted_goals NUMERIC(4, 2) NOT NULL,
    predicted_stage VARCHAR(50) NOT NULL,
    CONSTRAINT fk_team FOREIGN KEY (team_id) REFERENCES teams_state(team_id)
);

-- Matches Table: Tracks scheduled fixtures and live outcomes
CREATE TABLE matches (
    match_id VARCHAR(100) PRIMARY KEY,
    home_team_id VARCHAR(50) REFERENCES teams_state(team_id),
    away_team_id VARCHAR(50) REFERENCES teams_state(team_id),
    home_score INTEGER DEFAULT 0,
    away_score INTEGER DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'SCHEDULED', -- SCHEDULED, LIVE, FINISHED
    match_stage VARCHAR(50) NOT NULL, -- group, roundof32, roundof16, etc.
    kickoff_time TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Index Definitions: Optimized for rapid calculation lookups
CREATE INDEX idx_predictions_submission ON predictions(submission_id);
CREATE INDEX idx_teams_stage ON teams_state(current_stage);
CREATE INDEX idx_matches_status ON matches(status);
Implementation Sequence and Strategic Development StepsTo implement this design, development should proceed in a phased, five-step sequence:Phase 1: Models, Schema, and Ingestion LogicSet up the PostgreSQL database schema and configure indexing parameters.Build the CSV parser to handle input validation, row checks, and error reports.Implement team mapping files to link raw test IDs to corresponding national teams.Phase 2: Live Ingestion Pipelines and SchedulersCreate the polling engines for API-Football, ESPN, and Mundial '26 endpoints.Implement the scheduled state machine to adjust polling rates during active matches.Write database parsers to filter out penalty shootout goals from live data feeds.Phase 3: Analytical Engine and Dynamic SimulatorWrite the calculations to compute raw and normalized RMSE and Macro F1-scores.Implement the Monte Carlo simulator to project tournament outcomes.Build the cache layer to store user leaderboard rankings and percentiles.Phase 4: Delivery API and Interaction ChannelsBuild the core API backend using FastAPI or Express.js.Configure the Telegram Bot with the /start, /upload, /today, /yesterday, /bracket, and /rank commands [cite: user prompt].Implement the React PWA with local storage, CSV drag-and-drop, and SVG bracket elements.Phase 5: Notification Services and Integration TestingBuild the event parser to calculate metric shifts and generate message templates [cite: user prompt, 40].Integrate Telegram bot message delivery with web-push service worker APIs [cite: user prompt, 42].Execute integration tests using mock prediction files and simulated matches.Systems Conclusions and Future OutlookReplicating the live-tracking model of the March Mania bot for the World Cup 2026 Goal Prediction Challenge addresses a clear user-experience gap [cite: user prompt, 21]. By developing a dual-channel tracking architecture, developers can provide real-time updates to participants across both Telegram and web platforms [cite: user prompt].The decoupled design separates heavy analytical processing from client-side visualization, reducing operational costs during peak match times. Using static SVG templates allows for efficient visualization of the complex 48-team bracket on both mobile and desktop views.This spec document gives an AI developer agent a clear roadmap to implement the data parsers, ingestion schedulers, evaluation engines, and user interfaces [cite: user prompt, 21, 40]. Once deployed, the platform will offer an automated, personalized monitoring dashboard that helps users track their models' performance throughout the tournament [cite: user prompt, 17].