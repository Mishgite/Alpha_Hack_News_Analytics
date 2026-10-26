-- схема для новой пустой базы; поверх существующих таблиц этот файл не запускается
SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


-- при замене реакции сначала вычитаем прежний голос, затем добавляем новый
-- триггер работает и при изменениях через SQL, поэтому счётчики не зависят от репозитория
CREATE FUNCTION public.sync_reaction_totals() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                UPDATE reaction_totals SET
                    likes_cnt = likes_cnt - CASE WHEN OLD.reaction='like' THEN 1 ELSE 0 END,
                    dislikes_cnt = dislikes_cnt - CASE WHEN OLD.reaction='dislike' THEN 1 ELSE 0 END,
                    recalculated_at = now()
                WHERE news_id=OLD.news_id;
            END IF;
            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                INSERT INTO reaction_totals(news_id, likes_cnt, dislikes_cnt)
                VALUES (NEW.news_id, CASE WHEN NEW.reaction='like' THEN 1 ELSE 0 END,
                                    CASE WHEN NEW.reaction='dislike' THEN 1 ELSE 0 END)
                ON CONFLICT (news_id) DO UPDATE SET
                    likes_cnt = reaction_totals.likes_cnt + excluded.likes_cnt,
                    dislikes_cnt = reaction_totals.dislikes_cnt + excluded.dislikes_cnt,
                    recalculated_at = now();
            END IF;
            RETURN NULL;
        END;
        $$;


SET default_tablespace = '';

SET default_table_access_method = heap;


-- сохранённый разбор новости для компании с версиями данных, использованных при подготовке
CREATE TABLE public.ai_analyses (
    company_id text NOT NULL,
    company_context_id uuid NOT NULL,
    news_id uuid NOT NULL,
    news_content_hash text NOT NULL,
    result_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    sources_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    agent_trace_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    model_id text NOT NULL,
    prompt_version text NOT NULL,
    report_corpus_version text NOT NULL,
    agent_version text NOT NULL,
    retrieval_version text NOT NULL,
    context_hash text NOT NULL,
    cache_key text NOT NULL,
    status text DEFAULT 'ready'::text NOT NULL,
    expires_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_ai_analyses_status CHECK ((status = ANY (ARRAY['ready'::text, 'partial'::text])))
);


-- фрагмент отчёта со страницей, чтобы найденный текст можно было связать с источником
CREATE TABLE public.alfa_report_chunks (
    report_id uuid NOT NULL,
    page_num integer NOT NULL,
    chunk_no integer NOT NULL,
    text text NOT NULL,
    terms_tsvector tsvector GENERATED ALWAYS AS (to_tsvector('russian'::regconfig, text)) STORED NOT NULL,
    source_span_json jsonb,
    id uuid NOT NULL,
    CONSTRAINT ck_alfa_report_chunks_page_chunk CHECK (((page_num >= 1) AND (chunk_no >= 0)))
);


-- исходный аналитический документ и состояние его загрузки в поиск
CREATE TABLE public.alfa_reports (
    filename text NOT NULL,
    title text NOT NULL,
    report_date date,
    source_url text,
    file_hash text NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    id uuid NOT NULL,
    CONSTRAINT ck_alfa_reports_status CHECK ((status = ANY (ARRAY['pending'::text, 'ready'::text, 'failed'::text])))
);


-- состояние фонового задания, число попыток и срок, на который его забрал worker
CREATE TABLE public.analysis_jobs (
    user_id uuid NOT NULL,
    company_id text NOT NULL,
    news_id uuid NOT NULL,
    analysis_id uuid,
    status text DEFAULT 'queued'::text NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    error_code text,
    attempts integer DEFAULT 0 NOT NULL,
    idempotency_key text,
    lease_until timestamp with time zone,
    worker_id text,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_analysis_jobs_attempts CHECK ((attempts >= 0)),
    CONSTRAINT ck_analysis_jobs_status CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'ready'::text, 'failed'::text])))
);


-- вопрос пользователя и ответ по разбору, доступные только этому пользователю
CREATE TABLE public.analysis_questions (
    analysis_id uuid NOT NULL,
    user_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    question text NOT NULL,
    answer text NOT NULL,
    sources_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


-- профиль компании из исходных данных; неизвестные характеристики остаются пустыми
CREATE TABLE public.companies (
    id text NOT NULL,
    okved_code text,
    okved_name text,
    industry text,
    city text,
    region text,
    revenue numeric(24,2),
    group_id text,
    profile_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    profile_version text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    industry_code text,
    country_code text,
    registered_region_code text,
    operating_region_codes jsonb,
    known_factor_interests jsonb DEFAULT '[]'::jsonb NOT NULL
);


-- копия контекста компании, на которую ссылаются конкретная лента и разбор
CREATE TABLE public.company_context_snapshots (
    company_id text NOT NULL,
    context_hash text NOT NULL,
    payload_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_versions_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


-- значение признака вместе с файлом и полем, из которых оно получено
CREATE TABLE public.company_features (
    company_id text NOT NULL,
    feature_key text NOT NULL,
    value_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    origin_file text NOT NULL,
    origin_field text,
    calc_method text NOT NULL,
    confidence_type text,
    observed_at timestamp with time zone DEFAULT now() NOT NULL,
    id uuid NOT NULL
);


-- подтверждённая связь двух компаний: платёж, общая группа или связанное лицо
CREATE TABLE public.company_links (
    from_company_id text NOT NULL,
    to_company_id text NOT NULL,
    link_type text NOT NULL,
    pay_amount numeric(24,2),
    pay_count integer,
    source_dataset text NOT NULL,
    id uuid NOT NULL,
    CONSTRAINT ck_company_links_link_type CHECK ((link_type = ANY (ARRAY['payment'::text, 'same_group'::text, 'shared_person'::text])))
);


-- корпоративный интерес с весом и происхождением: правило или ручная настройка
CREATE TABLE public.company_tags (
    company_id text NOT NULL,
    tag_id text NOT NULL,
    origin text NOT NULL,
    reason text,
    rule_version text,
    base_weight numeric(6,4) DEFAULT '1'::numeric NOT NULL,
    CONSTRAINT ck_company_tags_origin CHECK ((origin = ANY (ARRAY['rule'::text, 'manual'::text]))),
    CONSTRAINT ck_company_tags_weight_range CHECK (((base_weight >= (0)::numeric) AND (base_weight <= (2)::numeric)))
);


-- место новости в выдаче, её баллы и копия отображаемых полей на момент сохранения
CREATE TABLE public.feed_snapshot_items (
    snapshot_id uuid NOT NULL,
    "position" integer NOT NULL,
    news_id uuid NOT NULL,
    final_score double precision NOT NULL,
    match_score double precision NOT NULL,
    freshness_score double precision NOT NULL,
    ranking_details jsonb DEFAULT '{}'::jsonb NOT NULL,
    features_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_feed_snapshot_items_position CHECK (("position" >= 0)),
    CONSTRAINT ck_feed_snapshot_items_score_range CHECK ((((match_score >= (0)::double precision) AND (match_score <= (1)::double precision)) AND ((freshness_score >= (0)::double precision) AND (freshness_score <= (1)::double precision)) AND ((final_score >= (0)::double precision) AND (final_score <= (1)::double precision))))
);


-- параметры конкретной выдачи: чей профиль использован, какой метод и до какого срока она доступна
CREATE TABLE public.feed_snapshots (
    user_id uuid NOT NULL,
    company_id text NOT NULL,
    company_context_id uuid NOT NULL,
    ranking_version text NOT NULL,
    ranking_method text NOT NULL,
    model_version text,
    feature_schema_version text NOT NULL,
    config_hash text NOT NULL,
    preference_context_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    candidate_cutoff_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_feed_snapshots_expiry CHECK ((expires_at > created_at)),
    CONSTRAINT ck_feed_snapshots_ranking_method CHECK ((ranking_method = ANY (ARRAY['weighted_formula_v1'::text, 'knn_cosine_v1'::text])))
);


-- история показов и действий; отличается от текущего состояния реакции пользователя
CREATE TABLE public.interaction_events (
    event_id uuid NOT NULL,
    user_id uuid NOT NULL,
    company_id text NOT NULL,
    snapshot_id uuid,
    news_id uuid NOT NULL,
    event_type text NOT NULL,
    payload_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_interaction_events_event_type CHECK ((event_type = ANY (ARRAY['impression'::text, 'open'::text, 'reaction_set'::text, 'reaction_clear'::text, 'tag_error'::text, 'analysis_feedback'::text])))
);


-- запись вызова модели с количеством токенов и стоимостью
CREATE TABLE public.llm_usage (
    task_type text NOT NULL,
    model_id text NOT NULL,
    news_id uuid,
    job_id uuid,
    input_tokens integer,
    output_tokens integer,
    estimated_cost_rub numeric(12,4),
    status text NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_llm_usage_nonnegative_usage CHECK (((input_tokens >= 0) AND (output_tokens >= 0) AND (estimated_cost_rub >= (0)::numeric))),
    CONSTRAINT ck_llm_usage_task_type CHECK ((task_type = ANY (ARRAY['tagger'::text, 'analyst'::text, 'verifier'::text, 'followup'::text])))
);


-- текст материала и признаки его текущей версии; старые признаки сбрасываются при обновлении
CREATE TABLE public.news (
    canonical_source text NOT NULL,
    external_id text,
    title text NOT NULL,
    text text NOT NULL,
    summary text,
    published_at timestamp with time zone NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    canonical_url text,
    url_hash text,
    content_hash text NOT NULL,
    story_cluster_id uuid,
    language text DEFAULT 'ru'::text NOT NULL,
    tagging_status text DEFAULT 'pending_tagging'::text NOT NULL,
    tagging_version text,
    extracted_features jsonb,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_news_external_id CHECK (((external_id IS NULL) OR (length(external_id) > 0))),
    CONSTRAINT ck_news_source_key CHECK (((external_id IS NOT NULL) OR (canonical_url IS NOT NULL))),
    CONSTRAINT ck_news_tag_status CHECK ((tagging_status = ANY (ARRAY['pending_tagging'::text, 'ready'::text, 'fallback'::text, 'failed'::text])))
);


-- ссылка на публикацию в источнике, связанная с сохранённой новостью
CREATE TABLE public.news_attributions (
    news_id uuid NOT NULL,
    source_code text NOT NULL,
    url text NOT NULL,
    published_at timestamp with time zone,
    external_id text,
    license_label text,
    id uuid NOT NULL
);


-- настройки источника и позиция, с которой продолжать загрузку
CREATE TABLE public.news_sources_registry (
    code text NOT NULL,
    kind text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    sync_interval_minutes integer DEFAULT 60 NOT NULL,
    last_success_at timestamp with time zone,
    source_cursor text,
    quota_state_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_news_sources_registry_positive_interval CHECK ((sync_interval_minutes > 0))
);


-- связь новости с темой; уверенность разметчика и вес качества хранятся отдельно
CREATE TABLE public.news_tags (
    news_id uuid NOT NULL,
    tag_id text NOT NULL,
    llm_confidence numeric(6,5),
    quality_weight numeric(6,4) DEFAULT '1'::numeric NOT NULL,
    tagger_version text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_news_tags_confidence_range CHECK (((llm_confidence >= (0)::numeric) AND (llm_confidence <= (1)::numeric))),
    CONSTRAINT ck_news_tags_weight_range CHECK (((quality_weight >= (0)::numeric) AND (quality_weight <= (2)::numeric)))
);


-- общие счётчики лайков и дизлайков, которые поддерживает триггер PostgreSQL
CREATE TABLE public.reaction_totals (
    news_id uuid NOT NULL,
    likes_cnt integer DEFAULT 0 NOT NULL,
    dislikes_cnt integer DEFAULT 0 NOT NULL,
    recalculated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_reaction_totals_nonnegative_counts CHECK (((likes_cnt >= 0) AND (dislikes_cnt >= 0)))
);


-- результат отдельной загрузки: сколько материалов получено и где возникли ошибки
CREATE TABLE public.source_runs (
    source_code text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    status text DEFAULT 'running'::text NOT NULL,
    fetched integer DEFAULT 0 NOT NULL,
    created_news integer DEFAULT 0 NOT NULL,
    duplicates integer DEFAULT 0 NOT NULL,
    errors_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    id uuid NOT NULL,
    CONSTRAINT ck_source_runs_counts CHECK (((fetched >= 0) AND (created_news >= 0) AND (duplicates >= 0))),
    CONSTRAINT ck_source_runs_status CHECK ((status = ANY (ARRAY['running'::text, 'ready'::text, 'partial'::text, 'failed'::text])))
);


-- котировка на указанное время; время данных и время получения сохраняются отдельно
CREATE TABLE public.stock_snapshots (
    ticker text NOT NULL,
    board text NOT NULL,
    captured_at timestamp with time zone DEFAULT now() NOT NULL,
    as_of timestamp with time zone NOT NULL,
    price numeric(24,6),
    previous_close numeric(24,6),
    change_abs numeric(24,6),
    change_percent numeric(12,6),
    turnover_rub numeric(24,2),
    volume numeric(24,6),
    market_cap_rub numeric(24,2),
    data_delay_minutes integer,
    id uuid NOT NULL,
    CONSTRAINT ck_stock_snapshots_nonnegative_delay CHECK ((data_delay_minutes >= 0))
);


-- биржевой инструмент; один тикер на разных режимах торгов считается разными записями
CREATE TABLE public.stocks (
    ticker text NOT NULL,
    board text NOT NULL,
    isin text,
    name text NOT NULL,
    sector text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


-- другое написание темы, которое нужно привести к одному id из справочника
CREATE TABLE public.tag_aliases (
    alias text NOT NULL,
    tag_id text NOT NULL
);


-- сообщение о неверной разметке; обычный дизлайк сюда не записывается
CREATE TABLE public.tag_feedback (
    user_id uuid NOT NULL,
    news_id uuid NOT NULL,
    wrong_tag_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    suggested_tag_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


-- общий справочник тем, с которым сверяется разметка новостей и интересы
CREATE TABLE public.tags (
    id text NOT NULL,
    display_name text NOT NULL,
    description text,
    category text,
    active boolean DEFAULT true NOT NULL
);


-- текущий лайк или дизлайк пользователя на новость
-- при снятии реакции строка удаляется
CREATE TABLE public.user_reactions (
    user_id uuid NOT NULL,
    news_id uuid NOT NULL,
    company_id text NOT NULL,
    reaction text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_user_reactions_reaction CHECK ((reaction = ANY (ARRAY['like'::text, 'dislike'::text])))
);


-- хэш токена сессии и её срок действия; сам токен не сохраняется
CREATE TABLE public.user_sessions (
    user_id uuid NOT NULL,
    token_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    id uuid NOT NULL
);


-- явное отключение темы пользователем без удаления самой темы из справочника
CREATE TABLE public.user_tag_overrides (
    user_id uuid NOT NULL,
    tag_id text NOT NULL,
    disabled boolean DEFAULT false NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


-- место для сохранённого пересчёта предпочтений; текущий репозиторий читает реакции напрямую
CREATE TABLE public.user_tag_preferences (
    user_id uuid NOT NULL,
    tag_id text NOT NULL,
    likes_cnt integer DEFAULT 0 NOT NULL,
    dislikes_cnt integer DEFAULT 0 NOT NULL,
    preference_weight numeric(6,4) DEFAULT '1'::numeric NOT NULL,
    recalculated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_user_tag_preferences_nonnegative_counts CHECK (((likes_cnt >= 0) AND (dislikes_cnt >= 0))),
    CONSTRAINT ck_user_tag_preferences_weight_range CHECK (((preference_weight >= (0)::numeric) AND (preference_weight <= (2)::numeric)))
);


-- тема, которую пользователь добавил сам; сохраняется при смене компании
CREATE TABLE public.user_tags (
    user_id uuid NOT NULL,
    tag_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


-- выбранная компания, должность для персонализации и отдельная роль доступа
CREATE TABLE public.users (
    city text NOT NULL,
    company_id text NOT NULL,
    job_role text DEFAULT 'other'::text NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    access_role text DEFAULT 'user'::text NOT NULL,
    CONSTRAINT ck_users_job_role CHECK ((job_role = ANY (ARRAY['ceo'::text, 'cfo'::text, 'treasury'::text, 'accountant'::text, 'employee'::text, 'other'::text])))
);


ALTER TABLE ONLY public.ai_analyses
    ADD CONSTRAINT pk_ai_analyses PRIMARY KEY (id);


ALTER TABLE ONLY public.alfa_report_chunks
    ADD CONSTRAINT pk_alfa_report_chunks PRIMARY KEY (id);


ALTER TABLE ONLY public.alfa_reports
    ADD CONSTRAINT pk_alfa_reports PRIMARY KEY (id);


ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT pk_analysis_jobs PRIMARY KEY (id);


ALTER TABLE ONLY public.analysis_questions
    ADD CONSTRAINT pk_analysis_questions PRIMARY KEY (id);


ALTER TABLE ONLY public.companies
    ADD CONSTRAINT pk_companies PRIMARY KEY (id);


ALTER TABLE ONLY public.company_context_snapshots
    ADD CONSTRAINT pk_company_context_snapshots PRIMARY KEY (id);


ALTER TABLE ONLY public.company_features
    ADD CONSTRAINT pk_company_features PRIMARY KEY (id);


ALTER TABLE ONLY public.company_links
    ADD CONSTRAINT pk_company_links PRIMARY KEY (id);


ALTER TABLE ONLY public.company_tags
    ADD CONSTRAINT pk_company_tags PRIMARY KEY (company_id, tag_id, origin);


ALTER TABLE ONLY public.feed_snapshot_items
    ADD CONSTRAINT pk_feed_snapshot_items PRIMARY KEY (snapshot_id, "position");


ALTER TABLE ONLY public.feed_snapshots
    ADD CONSTRAINT pk_feed_snapshots PRIMARY KEY (id);


ALTER TABLE ONLY public.interaction_events
    ADD CONSTRAINT pk_interaction_events PRIMARY KEY (event_id);


ALTER TABLE ONLY public.llm_usage
    ADD CONSTRAINT pk_llm_usage PRIMARY KEY (id);


ALTER TABLE ONLY public.news
    ADD CONSTRAINT pk_news PRIMARY KEY (id);


ALTER TABLE ONLY public.news_attributions
    ADD CONSTRAINT pk_news_attributions PRIMARY KEY (id);


ALTER TABLE ONLY public.news_sources_registry
    ADD CONSTRAINT pk_news_sources_registry PRIMARY KEY (code);


ALTER TABLE ONLY public.news_tags
    ADD CONSTRAINT pk_news_tags PRIMARY KEY (news_id, tag_id);


ALTER TABLE ONLY public.reaction_totals
    ADD CONSTRAINT pk_reaction_totals PRIMARY KEY (news_id);


ALTER TABLE ONLY public.source_runs
    ADD CONSTRAINT pk_source_runs PRIMARY KEY (id);


ALTER TABLE ONLY public.stock_snapshots
    ADD CONSTRAINT pk_stock_snapshots PRIMARY KEY (id);


ALTER TABLE ONLY public.stocks
    ADD CONSTRAINT pk_stocks PRIMARY KEY (ticker, board);


ALTER TABLE ONLY public.tag_aliases
    ADD CONSTRAINT pk_tag_aliases PRIMARY KEY (alias);


ALTER TABLE ONLY public.tag_feedback
    ADD CONSTRAINT pk_tag_feedback PRIMARY KEY (id);


ALTER TABLE ONLY public.tags
    ADD CONSTRAINT pk_tags PRIMARY KEY (id);


ALTER TABLE ONLY public.user_reactions
    ADD CONSTRAINT pk_user_reactions PRIMARY KEY (user_id, news_id);


ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT pk_user_sessions PRIMARY KEY (id);


ALTER TABLE ONLY public.user_tag_overrides
    ADD CONSTRAINT pk_user_tag_overrides PRIMARY KEY (user_id, tag_id);


ALTER TABLE ONLY public.user_tag_preferences
    ADD CONSTRAINT pk_user_tag_preferences PRIMARY KEY (user_id, tag_id);


ALTER TABLE ONLY public.user_tags
    ADD CONSTRAINT pk_user_tags PRIMARY KEY (user_id, tag_id);


ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);


ALTER TABLE ONLY public.ai_analyses
    ADD CONSTRAINT uq_ai_analyses_cache_key UNIQUE (cache_key);


ALTER TABLE ONLY public.alfa_report_chunks
    ADD CONSTRAINT uq_alfa_report_chunks_report_id UNIQUE (report_id, page_num, chunk_no);


ALTER TABLE ONLY public.alfa_reports
    ADD CONSTRAINT uq_alfa_reports_file_hash UNIQUE (file_hash);


ALTER TABLE ONLY public.ai_analyses
    ADD CONSTRAINT uq_analysis_id_company_news UNIQUE (id, company_id, news_id);


ALTER TABLE ONLY public.company_context_snapshots
    ADD CONSTRAINT uq_company_context_id_company UNIQUE (id, company_id);


ALTER TABLE ONLY public.company_context_snapshots
    ADD CONSTRAINT uq_company_context_snapshots_company_id UNIQUE (company_id, context_hash);


ALTER TABLE ONLY public.company_features
    ADD CONSTRAINT uq_company_features_company_id UNIQUE (company_id, feature_key, calc_method);


ALTER TABLE ONLY public.company_links
    ADD CONSTRAINT uq_company_links_from_company_id UNIQUE (from_company_id, to_company_id, link_type, source_dataset);


ALTER TABLE ONLY public.feed_snapshot_items
    ADD CONSTRAINT uq_feed_snapshot_items_snapshot_id UNIQUE (snapshot_id, news_id);


ALTER TABLE ONLY public.news_attributions
    ADD CONSTRAINT uq_news_attributions_news_id UNIQUE (news_id, url);


ALTER TABLE ONLY public.stock_snapshots
    ADD CONSTRAINT uq_stock_snapshots_ticker UNIQUE (ticker, board, as_of);


ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT uq_user_sessions_token_hash UNIQUE (token_hash);


CREATE INDEX ix_ai_analyses_company_news_created ON public.ai_analyses USING btree (company_id, news_id, created_at);


CREATE INDEX ix_alfa_report_chunks_fts ON public.alfa_report_chunks USING gin (terms_tsvector);


CREATE INDEX ix_analysis_jobs_company_news ON public.analysis_jobs USING btree (company_id, news_id);


CREATE INDEX ix_analysis_jobs_queue ON public.analysis_jobs USING btree (status, next_attempt_at, created_at);


CREATE INDEX ix_analysis_jobs_user_status ON public.analysis_jobs USING btree (user_id, status);


CREATE INDEX ix_companies_group_id ON public.companies USING btree (group_id);


CREATE INDEX ix_companies_industry ON public.companies USING btree (industry);


CREATE INDEX ix_company_links_from_company_id ON public.company_links USING btree (from_company_id);


CREATE INDEX ix_company_links_to_company_id ON public.company_links USING btree (to_company_id);


CREATE INDEX ix_feed_snapshots_expires_at ON public.feed_snapshots USING btree (expires_at);


CREATE INDEX ix_feed_snapshots_user_id ON public.feed_snapshots USING btree (user_id);


CREATE INDEX ix_interaction_events_received_at ON public.interaction_events USING btree (received_at);


CREATE INDEX ix_interaction_events_user_id ON public.interaction_events USING btree (user_id);


CREATE INDEX ix_news_content_hash ON public.news USING btree (content_hash);


CREATE INDEX ix_news_ready_published ON public.news USING btree (published_at) WHERE (tagging_status = 'ready'::text);


CREATE INDEX ix_news_story_cluster_id ON public.news USING btree (story_cluster_id);


CREATE INDEX ix_news_tags_tag_id ON public.news_tags USING btree (tag_id);


CREATE INDEX ix_questions_conversation ON public.analysis_questions USING btree (analysis_id, user_id, conversation_id, created_at);


CREATE INDEX ix_source_runs_source_code ON public.source_runs USING btree (source_code);


CREATE INDEX ix_user_sessions_user_id ON public.user_sessions USING btree (user_id);


CREATE INDEX ix_users_company_id ON public.users USING btree (company_id);


CREATE UNIQUE INDEX uq_analysis_jobs_idempotency ON public.analysis_jobs USING btree (user_id, idempotency_key) WHERE (idempotency_key IS NOT NULL);


CREATE UNIQUE INDEX uq_attribution_source_external ON public.news_attributions USING btree (source_code, external_id) WHERE (external_id IS NOT NULL);


CREATE UNIQUE INDEX uq_news_source_external ON public.news USING btree (canonical_source, external_id) WHERE (external_id IS NOT NULL);


CREATE UNIQUE INDEX uq_news_source_url_hash ON public.news USING btree (canonical_source, url_hash) WHERE (url_hash IS NOT NULL);


CREATE TRIGGER trg_reaction_totals AFTER INSERT OR DELETE OR UPDATE ON public.user_reactions FOR EACH ROW EXECUTE FUNCTION public.sync_reaction_totals();


ALTER TABLE ONLY public.ai_analyses
    ADD CONSTRAINT fk_ai_analyses_company_context_id_company_context_snapshots FOREIGN KEY (company_context_id, company_id) REFERENCES public.company_context_snapshots(id, company_id);


ALTER TABLE ONLY public.ai_analyses
    ADD CONSTRAINT fk_ai_analyses_company_id_companies FOREIGN KEY (company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.ai_analyses
    ADD CONSTRAINT fk_ai_analyses_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.alfa_report_chunks
    ADD CONSTRAINT fk_alfa_report_chunks_report_id_alfa_reports FOREIGN KEY (report_id) REFERENCES public.alfa_reports(id);


ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT fk_analysis_jobs_analysis_id_ai_analyses FOREIGN KEY (analysis_id, company_id, news_id) REFERENCES public.ai_analyses(id, company_id, news_id);


ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT fk_analysis_jobs_company_id_companies FOREIGN KEY (company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT fk_analysis_jobs_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT fk_analysis_jobs_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.analysis_questions
    ADD CONSTRAINT fk_analysis_questions_analysis_id_ai_analyses FOREIGN KEY (analysis_id) REFERENCES public.ai_analyses(id);


ALTER TABLE ONLY public.analysis_questions
    ADD CONSTRAINT fk_analysis_questions_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.company_context_snapshots
    ADD CONSTRAINT fk_company_context_snapshots_company_id_companies FOREIGN KEY (company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.company_features
    ADD CONSTRAINT fk_company_features_company_id_companies FOREIGN KEY (company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.company_links
    ADD CONSTRAINT fk_company_links_from_company_id_companies FOREIGN KEY (from_company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.company_links
    ADD CONSTRAINT fk_company_links_to_company_id_companies FOREIGN KEY (to_company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.company_tags
    ADD CONSTRAINT fk_company_tags_company_id_companies FOREIGN KEY (company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.company_tags
    ADD CONSTRAINT fk_company_tags_tag_id_tags FOREIGN KEY (tag_id) REFERENCES public.tags(id);


ALTER TABLE ONLY public.feed_snapshot_items
    ADD CONSTRAINT fk_feed_snapshot_items_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.feed_snapshot_items
    ADD CONSTRAINT fk_feed_snapshot_items_snapshot_id_feed_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.feed_snapshots(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.feed_snapshots
    ADD CONSTRAINT fk_feed_snapshots_company_context_id_company_context_snapshots FOREIGN KEY (company_context_id, company_id) REFERENCES public.company_context_snapshots(id, company_id);


ALTER TABLE ONLY public.feed_snapshots
    ADD CONSTRAINT fk_feed_snapshots_company_id_companies FOREIGN KEY (company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.feed_snapshots
    ADD CONSTRAINT fk_feed_snapshots_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.interaction_events
    ADD CONSTRAINT fk_interaction_events_company_id_companies FOREIGN KEY (company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.interaction_events
    ADD CONSTRAINT fk_interaction_events_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.interaction_events
    ADD CONSTRAINT fk_interaction_events_snapshot_id_feed_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.feed_snapshots(id) ON DELETE SET NULL;


ALTER TABLE ONLY public.interaction_events
    ADD CONSTRAINT fk_interaction_events_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.llm_usage
    ADD CONSTRAINT fk_llm_usage_job_id_analysis_jobs FOREIGN KEY (job_id) REFERENCES public.analysis_jobs(id) ON DELETE SET NULL;


ALTER TABLE ONLY public.llm_usage
    ADD CONSTRAINT fk_llm_usage_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.news_attributions
    ADD CONSTRAINT fk_news_attributions_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.news_attributions
    ADD CONSTRAINT fk_news_attributions_source_code_news_sources_registry FOREIGN KEY (source_code) REFERENCES public.news_sources_registry(code);


ALTER TABLE ONLY public.news
    ADD CONSTRAINT fk_news_canonical_source_news_sources_registry FOREIGN KEY (canonical_source) REFERENCES public.news_sources_registry(code);


ALTER TABLE ONLY public.news_tags
    ADD CONSTRAINT fk_news_tags_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.news_tags
    ADD CONSTRAINT fk_news_tags_tag_id_tags FOREIGN KEY (tag_id) REFERENCES public.tags(id);


ALTER TABLE ONLY public.reaction_totals
    ADD CONSTRAINT fk_reaction_totals_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.source_runs
    ADD CONSTRAINT fk_source_runs_source_code_news_sources_registry FOREIGN KEY (source_code) REFERENCES public.news_sources_registry(code);


ALTER TABLE ONLY public.stock_snapshots
    ADD CONSTRAINT fk_stock_snapshots_ticker_stocks FOREIGN KEY (ticker, board) REFERENCES public.stocks(ticker, board);


ALTER TABLE ONLY public.tag_aliases
    ADD CONSTRAINT fk_tag_aliases_tag_id_tags FOREIGN KEY (tag_id) REFERENCES public.tags(id);


ALTER TABLE ONLY public.tag_feedback
    ADD CONSTRAINT fk_tag_feedback_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.tag_feedback
    ADD CONSTRAINT fk_tag_feedback_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.user_reactions
    ADD CONSTRAINT fk_user_reactions_company_id_companies FOREIGN KEY (company_id) REFERENCES public.companies(id);


ALTER TABLE ONLY public.user_reactions
    ADD CONSTRAINT fk_user_reactions_news_id_news FOREIGN KEY (news_id) REFERENCES public.news(id);


ALTER TABLE ONLY public.user_reactions
    ADD CONSTRAINT fk_user_reactions_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT fk_user_sessions_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.user_tag_overrides
    ADD CONSTRAINT fk_user_tag_overrides_tag_id_tags FOREIGN KEY (tag_id) REFERENCES public.tags(id);


ALTER TABLE ONLY public.user_tag_overrides
    ADD CONSTRAINT fk_user_tag_overrides_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.user_tag_preferences
    ADD CONSTRAINT fk_user_tag_preferences_tag_id_tags FOREIGN KEY (tag_id) REFERENCES public.tags(id);


ALTER TABLE ONLY public.user_tag_preferences
    ADD CONSTRAINT fk_user_tag_preferences_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.user_tags
    ADD CONSTRAINT fk_user_tags_tag_id_tags FOREIGN KEY (tag_id) REFERENCES public.tags(id);


ALTER TABLE ONLY public.user_tags
    ADD CONSTRAINT fk_user_tags_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_company_id_companies FOREIGN KEY (company_id) REFERENCES public.companies(id);

CREATE TABLE public.processing_states (
    key text NOT NULL,
    value jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_processing_states PRIMARY KEY (key)
);

CREATE TABLE public.news_events (
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    matching_version text NOT NULL,
    automatic boolean DEFAULT true NOT NULL,
    CONSTRAINT pk_news_events PRIMARY KEY (id)
);

CREATE INDEX ix_news_event_window ON public.news (language, published_at);

CREATE TABLE public.analysis_feedback (
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    analysis_id uuid NOT NULL REFERENCES public.ai_analyses(id) ON DELETE CASCADE,
    useful boolean NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    PRIMARY KEY (user_id, analysis_id)
);



