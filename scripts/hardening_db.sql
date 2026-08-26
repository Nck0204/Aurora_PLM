-- ===========================================================================
--  Aurora - irrobustimento del registro delle operazioni
--  ---------------------------------------------------------------------
--  Rende la tabella "audit_logs" a sola aggiunta: ci si puo' scrivere una
--  riga nuova, non si puo' modificare o togliere una riga esistente.
--
--  PERCHE' NON BASTA IL PROGRAMMA. In app/services/audit.py c'e' una sola
--  funzione che scrive nel registro e non ce n'e' nessuna che lo corregge.
--  E' vero oggi e potrebbe non esserlo fra due anni: basta che qualcuno
--  aggiunga una funzione "per sistemare una riga sbagliata" e la garanzia
--  sparisce senza che nessuno se ne accorga. Un permesso che il database fa
--  rispettare, invece, non si dimentica: il programma **non riesce** a
--  correggere una riga nemmeno provandoci.
--
--  TRE STRATI, E FANNO TRE COSE DIVERSE.
--
--    1. i permessi (PARTE 1). L'utente con cui Aurora si collega ha SELECT e
--       INSERT su audit_logs, e non ha UPDATE ne' DELETE ne' TRUNCATE. Ferma
--       il programma, compreso il programma sbagliato di domani.
--
--    2. il proprietario separato (PARTE 2). I permessi di cui sopra se li
--       potrebbe ridare da solo il proprietario della tabella. Finche' il
--       proprietario e' aurora_app, quindi, la PARTE 1 e' una porta chiusa
--       con la chiave nella toppa. Passando la proprieta' a un ruolo diverso
--       - "aurora_owner", che non ha nemmeno il permesso di collegarsi - la
--       chiave la tiene chi amministra il database.
--
--    3. il grilletto (PARTE 2). Un trigger che rifiuta ogni UPDATE e ogni
--       DELETE, chiunque li faccia, compreso chi amministra il database.
--       Non e' una protezione contro chi vuole davvero manomettere il
--       registro - un superutente puo' disattivarlo - ma e' quello che ferma
--       lo sbaglio: il UPDATE senza WHERE scritto in psql alle otto di sera.
--
--  E IL QUARTO STRATO STA NEL DATO. Ogni voce porta l'impronta della voce
--  precedente. Non impedisce niente, ma rende **visibile** la manomissione
--  fatta scavalcando tutto questo: la catena non torna piu', e lo dice
--  scripts/verifica_audit.py. Vedi docs/DECISIONI.md, D-063.
--
--  ---------------------------------------------------------------------
--  COME SI ESEGUE. La procedura passo passo, con le verifiche, sta in
--  scripts/hardening_db.md. In due righe:
--
--    psql -U postgres -h localhost -d aurora -f scripts/hardening_db.sql
--
--  Va eseguito **come postgres** e **dopo** "alembic upgrade head": la
--  PARTE 2 vuole i diritti di superutente, e la migrazione e2f5a91c73d8
--  riempie le colonne delle righe gia' esistenti, cosa che dopo
--  l'irrobustimento non si potrebbe piu' fare.
--
--  Eseguito come aurora_app fa la sola PARTE 1 e lo dice; e' quello che si
--  fa sulla macchina di sviluppo, dove la password di postgres non serve a
--  nessuno.
--
--  E' IDEMPOTENTE: si puo' rieseguire quante volte si vuole.
-- ===========================================================================

\echo ''
\echo '=== Aurora - irrobustimento di audit_logs ==='
\echo ''


-- ---------------------------------------------------------------------------
--  PARTE 0 - controlli preliminari
-- ---------------------------------------------------------------------------
--  Meglio fermarsi subito con una frase chiara che a meta' strada con un
--  errore del database.

DO $$
BEGIN
    IF to_regclass('public.audit_logs') IS NULL THEN
        RAISE EXCEPTION
            'La tabella audit_logs non esiste in questo database. '
            'Eseguire prima "alembic upgrade head".';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'audit_logs' AND column_name = 'entry_hash'
    ) THEN
        RAISE EXCEPTION
            'La tabella audit_logs non ha la colonna entry_hash: le '
            'migrazioni non sono aggiornate. Eseguire "alembic upgrade head" '
            'prima di questo script.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aurora_app') THEN
        RAISE EXCEPTION
            'Il ruolo aurora_app non esiste. Vedere scripts/setup_postgres.md.';
    END IF;
END
$$;


-- ---------------------------------------------------------------------------
--  PARTE 1 - i permessi
-- ---------------------------------------------------------------------------
--  Questa parte la puo' eseguire anche aurora_app su se' stesso, finche' e'
--  proprietario della tabella. Da sola non basta - vedi la PARTE 2 - ma da
--  sola gia' impedisce al programma di correggere una riga del registro.

\echo '--- PARTE 1: i permessi su audit_logs ---'

-- Si toglie tutto e si ridanno le due cose che servono. Scritto cosi' invece
-- che con un REVOKE mirato perche' e' l'unico modo di essere sicuri di che
-- cosa resta: un REVOKE UPDATE lascerebbe in piedi i permessi che qualcuno
-- potrebbe aver concesso nel frattempo e di cui nessuno si ricorda.
REVOKE ALL ON TABLE audit_logs FROM aurora_app;
REVOKE ALL ON TABLE audit_logs FROM PUBLIC;

-- SELECT perche' il registro si consulta dalla pagina /registro e dalle
-- schede "Storico"; INSERT perche' ogni operazione ne aggiunge una riga.
-- **E nient'altro.** In particolare niente UPDATE, niente DELETE, niente
-- TRUNCATE e niente REFERENCES.
GRANT SELECT, INSERT ON TABLE audit_logs TO aurora_app;

\echo 'Permessi applicati: aurora_app ha SELECT e INSERT, e nient''altro.'


-- ---------------------------------------------------------------------------
--  PARTE 2 - il proprietario separato e il grilletto
-- ---------------------------------------------------------------------------
--  Serve il superutente. Se questo script viene eseguito da aurora_app, la
--  PARTE 2 si salta e lo dice: la PARTE 1 e' comunque stata applicata.
--
--  Tutto dentro un blocco DO con EXECUTE perche' CREATE ROLE e ALTER TABLE
--  non si possono scrivere sotto un IF in SQL normale.

DO $$
BEGIN
    IF NOT current_setting('is_superuser')::boolean THEN
        RAISE NOTICE '';
        RAISE NOTICE '--- PARTE 2 SALTATA ---';
        RAISE NOTICE 'Questa parte vuole i diritti di superutente e la '
                     'connessione corrente non li ha (utente %).', current_user;
        RAISE NOTICE 'La PARTE 1 e'' stata applicata lo stesso. Per completare '
                     'l''irrobustimento, rieseguire questo file come postgres:';
        RAISE NOTICE '  psql -U postgres -h localhost -d aurora -f scripts/hardening_db.sql';
        RAISE NOTICE '';
        RETURN;
    END IF;

    RAISE NOTICE '--- PARTE 2: proprietario separato e grilletto ---';

    -- Il ruolo proprietario. NOLOGIN: non e' un utente con cui ci si
    -- collega, e' soltanto un'intestazione. Nessuno lo usa mai per lavorare.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aurora_owner') THEN
        EXECUTE 'CREATE ROLE aurora_owner NOLOGIN';
        RAISE NOTICE 'Creato il ruolo aurora_owner.';
    END IF;

    -- Per poter assegnare la proprieta' a un ruolo bisogna esserne membri.
    -- Il superutente lo e' per definizione, ma dirlo esplicitamente rende lo
    -- script eseguibile anche da un amministratore non superutente che abbia
    -- CREATEROLE.
    EXECUTE 'GRANT aurora_owner TO ' || quote_ident(current_user);

    EXECUTE 'ALTER TABLE audit_logs OWNER TO aurora_owner';
    RAISE NOTICE 'audit_logs appartiene ad aurora_owner: aurora_app non puo'' '
                 'piu'' ridarsi i permessi da solo.';

    -- I permessi vanno riconcessi dopo il cambio di proprietario: cambiare
    -- proprietario non li tocca, ma se qualcuno riesegue lo script dopo aver
    -- fatto pulizia e' bene che ci siano comunque.
    EXECUTE 'REVOKE ALL ON TABLE audit_logs FROM aurora_app';
    EXECUTE 'GRANT SELECT, INSERT ON TABLE audit_logs TO aurora_app';

    -- Il grilletto. Ferma UPDATE e DELETE chiunque li faccia, superutente
    -- compreso: e' lo strato che protegge dallo sbaglio, non dal
    -- malintenzionato.
    EXECUTE $funzione$
        CREATE OR REPLACE FUNCTION audit_logs_solo_aggiunta()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $corpo$
        BEGIN
            RAISE EXCEPTION
                'audit_logs e'' un registro a sola aggiunta: % non e'' '
                'consentito. Le voci non si correggono e non si cancellano. '
                'Vedere scripts/hardening_db.md.', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $corpo$;
    $funzione$;

    EXECUTE 'ALTER FUNCTION audit_logs_solo_aggiunta() OWNER TO aurora_owner';

    EXECUTE 'DROP TRIGGER IF EXISTS audit_logs_niente_modifiche ON audit_logs';
    EXECUTE '
        CREATE TRIGGER audit_logs_niente_modifiche
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_solo_aggiunta()';

    EXECUTE 'DROP TRIGGER IF EXISTS audit_logs_niente_svuotamento ON audit_logs';
    EXECUTE '
        CREATE TRIGGER audit_logs_niente_svuotamento
        BEFORE TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_solo_aggiunta()';

    RAISE NOTICE 'Grilletti installati: UPDATE, DELETE e TRUNCATE su '
                 'audit_logs vengono rifiutati.';
END
$$;


-- ---------------------------------------------------------------------------
--  VERIFICA - che cosa e' rimasto
-- ---------------------------------------------------------------------------
--  Si stampa quello che c'e' adesso, invece di lasciar credere che sia
--  andato tutto bene. Nella prima tabella devono comparire due sole righe,
--  SELECT e INSERT; nella seconda il proprietario deve essere aurora_owner.

\echo ''
\echo '--- Verifica: i permessi di aurora_app su audit_logs ---'

SELECT privilege_type AS "permesso"
  FROM information_schema.table_privileges
 WHERE table_name = 'audit_logs'
   AND grantee = 'aurora_app'
 ORDER BY privilege_type;

\echo '--- Verifica: proprietario e grilletti ---'

SELECT tableowner AS "proprietario"
  FROM pg_tables
 WHERE tablename = 'audit_logs';

SELECT tgname AS "grilletto"
  FROM pg_trigger
 WHERE tgrelid = 'audit_logs'::regclass
   AND NOT tgisinternal
 ORDER BY tgname;

\echo ''
\echo 'Fatto. La prova che serve davvero e'' in scripts/hardening_db.md,'
\echo 'sezione "Verifica": un UPDATE con le credenziali di Aurora deve fallire.'
\echo ''
