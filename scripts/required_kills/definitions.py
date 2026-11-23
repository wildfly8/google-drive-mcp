"""The required-kill list as data: every entry is one deliberately wrong change to this repository.

Each entry has an id (G4-13), an invariant group (GAMMAS), a class, a one-line description and the
exact text edits that make the change. Edit paths are relative to the repository root and each old text
must occur exactly once. `run.py` applies one entry at a time to a copy of the repository and runs the
test suite on the copy: the suite must fail. See specs/006-required-kills/spec.md for what the entries
mean and who owns them: the owner decides what is on the list, and an agent may propose entries but may
not remove or downgrade one to make the suite pass.

class    must    flips a must-transition (safety, paywall, completeness)
         should  makes the service worse or less faithful without being unsafe
         may     changes only speed or order
expect   "kill"     the suite must fail on it
         "survive"  no test can tell it from the real code (equivalent, unreachable, or a second layer
                    enforces the same property); `note` says why. Removing the redundant layers together
                    is a second-order entry (id with S) and must be killed.
killer   optional: the one test (node id) that kills the entry when run alone. `run.py --confirm` uses it
         instead of the failures recorded in a full run, for an entry whose recorded failures only happen
         after other tests have run.
"""

from __future__ import annotations

from dataclasses import dataclass

S = "src/google_drive_mcp/"


@dataclass
class Mutant:
    id: str
    gamma: str
    title: str
    edits: list[tuple[str, str, str]]
    sev: str = "must"
    expect: str = "kill"
    note: str = ""
    killer: str = ""


GAMMAS: dict[str, str] = {
    "G1": "Scope: nothing outside kb is ever listed or read (Art. I, VII; AC-FR-025)",
    "G2": "Read-only: no write path to Drive (Art. V)",
    "G3": "Authentication: every drive_* call needs a valid access token (Art. VII)",
    "G4": "Paywall: no token, code or cookie without an active subscription; fails closed",
    "G5": "Completeness is visible: PARTIAL vs EMPTY, never silent (Art. X)",
    "G6": "Exactness and determinism: literal means literal; same order every time (Art. IX)",
    "G7": "Ephemerality, freshness, isolation: nothing kept, nothing shared between calls (Art. I, III)",
    "G8": "Provenance and citation: one cite line, no locator in results (Art. VIII)",
    "G9": "Failure taxonomy: classified, and no existence oracle (Art. XI)",
    "G10": "Secrets and logs: no token, no document text in logs (Art. VII, XI)",
    "G11": "Abuse limits: the per-call ceilings against bulk extraction",
    "G12": "Documents are data, not instructions (Art. VI)",
    "G13": "Speed: the three engineering invariants from the latency fixes",
    "G14": "OAuth and identity surface: no SSRF, no code theft, no account takeover (Art. VII)",
}

MUTANTS: list[Mutant] = []


def add(id, gamma, title, edits, sev="must", expect="kill", note="", killer=""):
    MUTANTS.append(Mutant(id, gamma, title, edits, sev, expect, note, killer))


# --------------------------------------------------------------------------- G1 scope
RS = S + "domain/retrieval_scope.py"
CH = S + "access_control/chain.py"
MW = S + "mcp/middleware.py"
TL = S + "mcp/tools.py"
LS = S + "infra/google_drive/list.py"

add("G1-01", "G1", "is_inside_tree falls through to True: any id the lookup returns is allowed [POSITIVE CONTROL]",
    [(RS, "        stack.extend(tree.get(current, ()))\n    return False\n",
      "        stack.extend(tree.get(current, ()))\n    return True\n")])
add("G1-02", "G1", "membership check dropped: an id Drive knows is allowed wherever it lives",
    [(CH, "                if parents is None or not is_inside_tree(fid, parents, allowed, tree):\n",
      "                if parents is None:\n")])
add("G1-03", "G1", "a named folder_id is not checked at all (only file ids are)",
    [(CH, "    named = [*named_files, *([scope.folder_id] if scope.folder_id else [])]\n",
      "    named = [*named_files]\n")])
add("G1-04", "G1", "a missing id raises FILE_NOT_FOUND instead of the refusal (existence oracle)",
    [(CH, "            if exc.error.category == ErrorCategory.FILE_NOT_FOUND:\n                return None\n            raise\n",
      "            raise\n")])
add("G1-05", "G1", "the lookups stop at the first refusal (call count and timing reveal which id failed)",
    [(CH, "concurrent=needs_tree) as fetching:", "concurrent=False) as fetching:")],
    note="tied to AC-FR-025: same Drive calls for outside, missing and ungranted ids")
add("G1-06", "G1", "no allow-list configured no longer refuses",
    [(CH, '    if not allowed:\n        return _refuse(principal_id, StepFailed.mcp_authorization, "no_allowed_folder")\n',
      '    if False:\n        return _refuse(principal_id, StepFailed.mcp_authorization, "no_allowed_folder")\n')])
add("G1-07", "G1", "omitted folder is widened to the Drive root instead of kb",
    [(RS, '        arguments["folder_id"] = allowed\n', '        arguments["folder_id"] = "root"\n')])
add("G1-08", "G1", "omitted folder is no longer narrowed to kb (all three rewrite layers go with it)",
    [(RS, '    if not _named(arguments.get("folder_id")) and not _names_files(arguments):\n        arguments["folder_id"] = allowed\n',
      '    if False:\n        arguments["folder_id"] = allowed\n')])
add("G1-09", "G1", "rewrite layer 1 only (handle_tool)", [(TL, "    apply_allowed_folder(args, runtime.settings.drive_allowed_folder_id)\n", "    pass\n")],
    expect="survive")
add("G1-10", "G1", "rewrite layer 2 only (middleware.authorize)", [(MW, "    if allowed:\n        apply_allowed_folder(arguments, allowed)\n", "    if allowed:\n        pass\n")],
    expect="survive")
add("G1-11", "G1", "rewrite layer 3 only (evaluate_chain)", [(CH, "    apply_allowed_folder(rewritten, allowed)\n", "    pass\n")],
    expect="survive")
add("G1-12", "G1", "all three rewrite layers removed", [
    (TL, "    apply_allowed_folder(args, runtime.settings.drive_allowed_folder_id)\n", "    pass\n"),
    (MW, "    if allowed:\n        apply_allowed_folder(arguments, allowed)\n", "    if allowed:\n        pass\n"),
    (CH, "    apply_allowed_folder(rewritten, allowed)\n", "    pass\n")])
add("G1-13", "G1", "whole-grant refusal removed (only the last of five layers against an unscoped call)",
    [(CH, '    if scope.default_whole_grant:\n        return _refuse(principal_id, StepFailed.mcp_authorization, "whole_grant_refused")\n',
      '    if False:\n        return _refuse(principal_id, StepFailed.mcp_authorization, "whole_grant_refused")\n')],
    expect="survive")
add("G1-14", "G1", "tree listing skipped: nested folders refused", [(CH, "            tree = _tree() if needs_tree else {}\n", "            tree = {}\n")], sev="should")
add("G1-15", "G1", "ancestor walk stops following the tree: nested files refused",
    [(RS, "        stack.extend(tree.get(current, ()))\n", "        pass\n")], sev="should")
add("G1-16", "G1", "tree builder trusts a lister that returns folders not under the frontier",
    [(RS, "            if not fid or fid in known or not level.intersection(parents):\n", "            if not fid or fid in known:\n")])
add("G1-17", "G1", "file_ids inside the named folder check removed (file_outside_folder)",
    [(CH, "                if not is_inside_tree(fid, parents_of[fid], scope.folder_id, tree):\n", "                if False:\n")],
    sev="should", note="narrows within kb; not a kb-boundary leak")
add("G1-18", "G1", "walker scope check removed for named files",
    [(LS, "        if not trust and not is_within_scope(file.id, scope, lookup):\n            return\n", "        if False:\n            return\n")],
    sev="should", expect="survive")
add("G1-19", "G1", "a listing is no longer filtered to real children (stale or over-broad index entry)",
    [(LS, "    kept = [f for f in files if folder_id in f.parents]\n", "    kept = files\n")])
add("G1-20", "G1", "trashed files are listed and searched",
    [(LS, "        if file.trashed and not include_trashed:\n            return\n", "        if False:\n            return\n")], sev="should")
add("G1-21", "G1", "whitespace-only file id counts as a named file (skips the kb rewrite)",
    [(RS, "    return isinstance(value, str) and bool(value.strip())\n", "    return isinstance(value, str) and bool(value)\n")], sev="should",
    note="behaviour only: both outcomes stay inside kb")
add("G1-22", "G1", "an explicitly named subfolder is replaced by kb root",
    [(RS, '    if not _named(arguments.get("folder_id")) and not _names_files(arguments):\n',
      '    if not _names_files(arguments):\n')], sev="should")
add("G1-23", "G1", "startup accepts a Drive root as the allow-list",
    [(S + "access_control/allowed_folder.py",
      '    if not meta.get("parents") or root_id in {folder_id, meta.get("id")}:\n', "    if False:\n")])
add("G1-24", "G1", "startup accepts a non-folder as the allow-list",
    [(S + "access_control/allowed_folder.py",
      '    if meta.get("mime_type") != FOLDER_MIME:\n        raise ValueError("DRIVE_ALLOWED_FOLDER_ID is not a folder.")\n',
      '    if False:\n        raise ValueError("DRIVE_ALLOWED_FOLDER_ID is not a folder.")\n')])
add("G1-25", "G1", "server starts with no allow-list configured",
    [(S + "infra/config.py", "        if not folder:\n            raise ValueError(\n                \"DRIVE_ALLOWED_FOLDER_ID is not set.",
      "        if False:\n            raise ValueError(\n                \"DRIVE_ALLOWED_FOLDER_ID is not set.")])
add("G1-26", "G1", "startup accepts alias 'root' as the allow-list",
    [(S + "infra/config.py", "        if folder.lower() in DRIVE_SPACE_ALIASES or not _FOLDER_ID_RE.fullmatch(folder):\n",
      "        if False:\n")])

# ----------------------------------------------------------------------- G2 read-only
CL = S + "infra/google_drive/client.py"
ANCHOR = "    def export(self, file_id: str, mime: str) -> str:\n"


def inject(call: str):
    body = f"    def _mutant_write(self, file_id: str) -> None:\n        {call}\n\n"
    return [(CL, ANCHOR, body + ANCHOR)]


add("G2-01", "G2", "Google scope widened from drive.readonly to drive",
    [(S + "infra/google_auth/refresh_token.py",
      'DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"',
      'DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive"')])
add("G2-02", "G2", "a files().delete( method appears", inject("self._service.files().delete(fileId=file_id).execute(http=self._http())"))
add("G2-03", "G2", "a files().update( method appears (trash/rename)", inject('self._service.files().update(fileId=file_id, body={"trashed": True}).execute(http=self._http())'))
add("G2-04", "G2", "a files().create( method appears", inject('self._service.files().create(body={"name": "x"}).execute(http=self._http())'))
add("G2-05", "G2", "a permissions().create( method appears (share)", inject('self._service.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute(http=self._http())'))
add("G2-06", "G2", "a files().copy( method appears", inject("self._service.files().copy(fileId=file_id, body={}).execute(http=self._http())"))
add("G2-07", "G2", "a files().emptyTrash( method appears", inject("self._service.files().emptyTrash().execute(http=self._http())"))
add("G2-08", "G2", "a comments().create( method appears", inject('self._service.comments().create(fileId=file_id, body={"content": "x"}, fields="id").execute(http=self._http())'))
add("G2-09", "G2", "a revisions().delete( method appears", inject("self._service.revisions().delete(fileId=file_id, revisionId='1').execute(http=self._http())"))
add("G2-10", "G2", "a raw HTTP DELETE to the Drive API appears", inject('httplib2.Http().request(f"https://www.googleapis.com/drive/v3/files/{file_id}", method="DELETE")'))
add("G2-11", "G2", "a drives().create( method appears", inject('self._service.drives().create(requestId="x", body={"name": "x"}).execute(http=self._http())'))
add("G2-12", "G2", "tool advertises readOnlyHint=False", [(S + "mcp/tool_schema.py", "    readOnlyHint=True,\n", "    readOnlyHint=False,\n")])
add("G2-13", "G2", "tool advertises destructiveHint=True", [(S + "mcp/tool_schema.py", "    destructiveHint=False,\n", "    destructiveHint=True,\n")])
add("G2-14", "G2", "a fifth tool name (drive_delete) joins the read-only tool set",
    [(TL, 'READ_ONLY_TOOLS = ("drive_ls", "drive_find", "drive_read", "drive_grep")',
      'READ_ONLY_TOOLS = ("drive_ls", "drive_find", "drive_read", "drive_grep", "drive_delete")')])

# ------------------------------------------------------------------- G3 authentication
TK = S + "infra/mcp_auth/tokens.py"
JW = S + "infra/mcp_auth/jwt.py"
add("G3-01", "G3", "token type not checked (a refresh or code token works as an access token)",
    [(TK, '    if payload.get("typ") != typ:\n        return None\n', '    if False:\n        return None\n')])
add("G3-02", "G3", "issuer not checked", [(TK, '    if payload.get("iss") != issuer_url(settings):\n        return None\n', '    if False:\n        return None\n')])
add("G3-03", "G3", "audience not checked (a token for another resource works)", [(TK, '    if payload.get("aud") != audience:\n        return None\n', '    if False:\n        return None\n')])
add("G3-04", "G3", "expiry not checked", [(TK, "    if not isinstance(exp, int) or exp < _now():\n        return None\n", "    if not isinstance(exp, int):\n        return None\n")])
add("G3-05", "G3", "scope not checked", [(TK, '    if payload.get("scope") != MCP_OAUTH_SCOPE:\n        return None\n', '    if False:\n        return None\n')])
add("G3-06", "G3", "signature not compared (any well-formed token passes)",
    [(JW, "    if len(sig) != len(expected) or not hmac.compare_digest(sig, expected):\n        return None\n",
      "    if len(sig) != len(expected):\n        return None\n")])
add("G3-07", "G3", "JWT alg header not checked", [(JW, '    if header.get("alg") != "HS256" or header.get("typ") != "JWT":\n        return None\n', '    if False:\n        return None\n')],
    note="a valid signature does not make the algorithm header redundant: a test signs under another header")
add("G3-08", "G3", "chain no longer verifies the caller", [(CH, "    if not verify_caller(authorization):\n", "    if False:\n")],
    note="second layer: handle_tool verifies first")
add("G3-09", "G3", "handle_tool no longer verifies the caller", [(TL, "    if not verify_authorization_header(authorization, runtime.settings):\n", "    if False:\n")],
    note="second layer: the chain verifies next")
add("G3-10", "G3", "authentication removed in both layers", [
    (CH, "    if not verify_caller(authorization):\n", "    if False:\n"),
    (TL, "    if not verify_authorization_header(authorization, runtime.settings):\n", "    if False:\n")])
add("G3-11", "G3", "Google credentials are minted before the caller is authenticated",
    [(CH, "    if not verify_caller(authorization):\n        return AuthorizationDecision(\n",
      "    if mint_credentials is not None:\n        mint_credentials()\n    if not verify_caller(authorization):\n        return AuthorizationDecision(\n")])
add("G3-12", "G3", "consent password: an unset (empty) secret accepts an empty answer",
    [(S + "infra/mcp_auth/bearer.py", '    if provided is None or expected == "":\n', "    if provided is None:\n")])

# ------------------------------------------------------------------------- G4 paywall
PV = S + "infra/mcp_auth/provider.py"
ST = S + "infra/billing/stripe_api.py"
EN = S + "infra/billing/entitlement.py"
SV = S + "mcp/server.py"
add("G4-01", "G4", "canceled counts as entitled", [(ST, '_ENTITLED = frozenset({"active", "trialing"})', '_ENTITLED = frozenset({"active", "trialing", "canceled"})')])
add("G4-02", "G4", "past_due counts as entitled", [(ST, '_ENTITLED = frozenset({"active", "trialing"})', '_ENTITLED = frozenset({"active", "trialing", "past_due"})')])
add("G4-03", "G4", "billing outage fails open (is_subscription_active)", [(ST, "        return self.subscription_state(customer_id) is True\n", "        return self.subscription_state(customer_id) is not False\n")])
add("G4-04", "G4", "billing outage fails open (provider._active)", [(PV, "        return bool(customer_id) and await self._subscription_state(str(customer_id)) is True\n", "        return bool(customer_id) and await self._subscription_state(str(customer_id)) is not False\n")])
add("G4-05", "G4", "authorize issues a code without checking the subscription", [(PV, "            if not await self._active(scid):\n", "            if False:\n")])
add("G4-06", "G4", "code exchange does not refuse an inactive subscription",
    [(PV, '            if not state:\n                raise TokenError(error="invalid_grant", error_description="subscription inactive")\n',
      '            if False:\n                raise TokenError(error="invalid_grant", error_description="subscription inactive")\n')])
add("G4-07", "G4", "code with no customer id counts as subscribed",
    [(PV, "mcp_subscription_required:\n            state = await self._subscription_state(sid) if sid else False\n",
      "mcp_subscription_required:\n            state = await self._subscription_state(sid) if sid else True\n")])
add("G4-08", "G4", "refresh does not refuse a lapsed subscription",
    [(PV, '                if not state:\n                    raise TokenError(\n                        error="invalid_grant", error_description="subscription inactive"\n                    )\n',
      '                if False:\n                    raise TokenError(\n                        error="invalid_grant", error_description="subscription inactive"\n                    )\n')])
add("G4-09", "G4", "refresh token with no customer id counts as subscribed",
    [(PV, "mcp_subscription_required:\n                state = await self._subscription_state(sid) if sid else False\n",
      "mcp_subscription_required:\n                state = await self._subscription_state(sid) if sid else True\n")])
add("G4-10", "G4", "a Stripe outage reads as 'subscription inactive' (permanent) instead of 'unavailable' (retry)",
    [(PV, '                    raise BillingUnavailable("subscription check unavailable")\n                if not state:',
      '                    raise TokenError(error="invalid_grant", error_description="subscription inactive")\n                if not state:')],
    sev="should")
add("G4-11", "G4", "a failed refresh keeps the refresh token spent (subscriber locked out by a Stripe blip)",
    [(PV, "            self._revoked_jti.discard(jti)\n            raise\n", "            raise\n")], sev="should")
add("G4-12", "G4", "refresh token is not reserved before the Stripe check (two refreshes can both succeed)",
    [(PV, '        self._revoked_jti.add(jti, int(claims["exp"]))\n', "        pass\n")])
add("G4-13", "G4", "authorization code can be used twice (jti never recorded)", [(PV, '        self._used_code_jti.add(jti, int(claims["exp"]))\n', "        pass\n")])
add("G4-14", "G4", "authorization code replay check removed", [(PV, "        if jti in self._used_code_jti:\n            raise TokenError(", "        if False:\n            raise TokenError(")])
add("G4-15", "G4", "revoked access token is still accepted",
    [(PV, '        if str(claims["jti"]) in self._revoked_jti:\n            return None\n        return AccessToken(', "        return AccessToken(")])
add("G4-16", "G4", "refresh re-issue drops the customer id (next refresh cannot check the subscription)",
    [(PV, "        return self._issue_tokens(client.client_id, connect_id=cid, scid=sid)\n", "        return self._issue_tokens(client.client_id, connect_id=cid, scid=None)\n")], sev="should")
add("G4-17", "G4", "Checkout session need not be complete", [(ST, '            if status != "complete" or payment not in {"paid", "no_payment_required"}:\n', '            if payment not in {"paid", "no_payment_required"}:\n')])
add("G4-18", "G4", "unpaid Checkout session grants access", [(ST, '            if status != "complete" or payment not in {"paid", "no_payment_required"}:\n', '            if status != "complete" or payment not in {"paid", "no_payment_required", "unpaid"}:\n')])
add("G4-19", "G4", "Checkout success link works for anyone (reference binding dropped)", [(ST, "            if not isinstance(carried, str) or not hmac.compare_digest(carried, reference):\n", "            if not isinstance(carried, str):\n")])
add("G4-20", "G4", "Stripe webhook signature not compared", [(ST, "    return hmac.compare_digest(expected, v1)", "    return True")])
add("G4-21", "G4", "Stripe webhook accepted when no signing secret is set", [(ST, "    if not secret or not header or not payload:\n        return False\n", "    if not header or not payload:\n        return False\n")])
add("G4-22", "G4", "Stripe webhook replay window removed", [(ST, "    if abs(current - timestamp) > 300:\n        return False\n", "    if False:\n        return False\n")])
add("G4-23", "G4", "entitlement cookie: type not checked", [(EN, '    if payload.get("typ") != TYP_ENTITLEMENT:\n        return None\n', "    if False:\n        return None\n")])
add("G4-24", "G4", "entitlement cookie: audience not checked", [(EN, '    if payload.get("aud") != entitlement_audience(settings):\n        return None\n', "    if False:\n        return None\n")])
add("G4-25", "G4", "entitlement cookie: expiry not checked", [(EN, "    if not isinstance(exp, int) or exp < _now():\n        return None\n", "    if not isinstance(exp, int):\n        return None\n")])
add("G4-26", "G4", "entitlement cookie: customer id shape not checked", [(EN, '    if not isinstance(scid, str) or not scid.startswith("cus_"):\n        return None\n', "    if not isinstance(scid, str):\n        return None\n")], sev="should")
add("G4-27", "G4", "entitlement cookie is trusted without verifying it", [(SV, "            scid = verify_entitlement(raw, self.settings)\n", "            scid = raw\n")])
add("G4-28", "G4", "unsubscribed browser is not sent to /subscribe", [(SV, "                    if not scid:\n                        await send(\n", "                    if False:\n                        await send(\n")])
add("G4-29", "G4", "entitlement cookie loses HttpOnly", [(EN, '        httponly=True,\n        samesite="lax",\n', '        httponly=False,\n        samesite="lax",\n')], sev="should")
add("G4-30", "G4", "deploy script no longer sets MCP_SUBSCRIPTION_REQUIRED",
    [("scripts/deploy-cloud-run.sh", '  DEPLOY_ENV="${DEPLOY_ENV},MCP_SUBSCRIPTION_REQUIRED=true"\n', '  DEPLOY_ENV="${DEPLOY_ENV}"\n')])
add("G4-31", "G4", "deploy script deploys without the paywall secrets instead of refusing",
    [("scripts/deploy-cloud-run.sh", 'Refusing to deploy without the paywall." >&2\n  exit 1\n', 'Refusing to deploy without the paywall." >&2\n  true\n')])

# ---------------------------------------------------------------------- G5 completeness
GR = S + "retrieval/grep.py"
LSF = S + "retrieval/ls.py"
FD = S + "retrieval/find.py"
RD = S + "retrieval/read.py"
add("G5-01", "G5", "grep: files set aside for the byte cap no longer make the result PARTIAL", [(GR, "    if truncated_bytes or deferred:\n", "    if truncated_bytes:\n")])
add("G5-02", "G5", "grep: stopping at the file cap is reported as COMPLETE/EMPTY", [(GR, "    if resume:\n        return _coverage(\n", "    if False:\n        return _coverage(\n")])
add("G5-03", "G5", "grep: stopping at the match cap is reported as COMPLETE", [(GR, "    if hit_match_cap:\n        return _coverage(\n", "    if False:\n        return _coverage(\n")])
add("G5-04", "G5", "grep: a rate limit is reported as COMPLETE/EMPTY", [(GR, "    if rate_limited:\n        return _coverage(\n", "    if False:\n        return _coverage(\n")])
add("G5-05", "G5", "grep: a cut file listing (time) no longer makes the result PARTIAL", [(GR, "    if walk.time_exceeded or stopped_for_time:\n", "    if stopped_for_time:\n")], expect="survive")
add("G5-06", "G5", "grep: skipped unsupported files are not reported", [(GR, "    if skipped_unsupported and (searchable or cursor):\n        return _coverage(\n", "    if False:\n        return _coverage(\n")])
add("G5-07", "G5", "grep: zero hits reports COMPLETE instead of EMPTY", [(GR, "        return _coverage(status=OperationStatus.EMPTY, **common)\n", "        return _coverage(status=OperationStatus.COMPLETE, **common)\n")])
add("G5-08", "G5", "grep: a cut listing is scanned anyway", [(GR, "    listing_complete = not walk.time_exceeded and not walk.rate_limited\n", "    listing_complete = True\n")])
add("G5-09", "G5", "grep: file cap off by one", [(GR, "            if files_scanned >= budget.max_files:\n", "            if files_scanned > budget.max_files:\n")])
add("G5-10", "G5", "grep: a file that does not fit the byte budget is dropped, neither scanned nor deferred",
    [(GR, "                    deferred.append(file.id)\n                    if prefetch is not None:\n                        prefetch.discard(index)\n",
      "                    if prefetch is not None:\n                        prefetch.discard(index)\n")])
add("G5-11", "G5", "grep: files after byte exhaustion are dropped, not deferred",
    [(GR, "                    deferred.extend(item.id for item in files[index:] if _searchable(item))\n                    break\n", "                    break\n")])
add("G5-12", "G5", "grep: more matches in the same file are not reported as PARTIAL", [(GR, "            if more_in_file:\n                hit_match_cap = True\n", "            if more_in_file:\n                hit_match_cap = False\n")])
add("G5-13", "G5", "grep: a stopped scan gives no next_cursor (host cannot continue)", [(GR, "        next_cursor = last_scanned_id or cursor or None\n", "        next_cursor = None\n")])
add("G5-14", "G5", "grep: resuming inside a file skips the rest of that file", [(GR, "        files = files[start:] if skip else files[start + 1 :]\n", "        files = files[start + 1 :]\n")])
add("G5-15", "G5", "grep: a single named file can be deferred (and so never read)", [(GR, "            if not single_target:\n                remaining = budget.max_bytes_per_operation - budget.bytes_seen\n", "            if True:\n                remaining = budget.max_bytes_per_operation - budget.bytes_seen\n")])
add("G5-16", "G5", "grep: nothing searchable (all unsupported) reads as EMPTY, not an error", [(GR, "    if searchable == 0 and skipped_unsupported and not stopped and not cursor:\n", "    if False:\n")])
add("G5-17", "G5", "grep: wrong partial reason for the match cap", [(GR, "            partial_reason=PartialReason.max_matches.value,\n", "            partial_reason=PartialReason.max_files.value,\n")], sev="should")
add("G5-18", "G5", "ls: a truncated listing is reported as COMPLETE", [(LSF, "    if walk.more or walk.truncated:\n", "    if walk.more:\n")], expect="survive")
add("G5-19", "G5", "ls: an empty folder is reported as COMPLETE", [(LSF, '        return {"status": OperationStatus.EMPTY.value, "children": []}\n', '        return {"status": OperationStatus.COMPLETE.value, "children": []}\n')])
add("G5-20", "G5", "ls: a rate limit is reported as COMPLETE", [(LSF, "    if walk.rate_limited:\n        return {\n", "    if False:\n        return {\n")])
add("G5-21", "G5", "ls: a listing cut by time is reported as COMPLETE", [(LSF, '    if budget.time_exceeded():\n        return {\n            "status": OperationStatus.PARTIAL.value,\n            "partial_reason": PartialReason.max_execution_time.value,\n            "children": children,\n', '    if False:\n        return {\n            "status": OperationStatus.PARTIAL.value,\n            "partial_reason": PartialReason.max_execution_time.value,\n            "children": children,\n')])
add("G5-22", "G5", "find: hitting max_results is reported as COMPLETE", [(FD, "    if walk.truncated:\n        return {\n", "    if False:\n        return {\n")])
add("G5-23", "G5", "find: a cut by time is reported as COMPLETE", [(FD, "    if walk.time_exceeded:\n        return {\n", "    if False:\n        return {\n")])
add("G5-24", "G5", "find: a rate limit is reported as COMPLETE", [(FD, "    if walk.rate_limited:\n        return {\n", "    if False:\n        return {\n")])
add("G5-25", "G5", "read: a truncated read is reported as COMPLETE", [(RD, "OperationStatus.PARTIAL.value if truncated else OperationStatus.COMPLETE.value", "OperationStatus.COMPLETE.value")])
add("G5-26", "G5", "read: a truncated read carries no partial_reason", [(RD, '    if truncated:\n        result["partial_reason"] = PartialReason.max_bytes.value\n', "    if False:\n        pass\n")], sev="should")

# ------------------------------------------------------------- G6 exactness / determinism
RX = S + "infra/exact_search/regex.py"
add("G6-01", "G6", "a literal pattern is compiled as a regex (re.escape dropped)", [(RX, "        return re.compile(re.escape(pattern), flags)\n", "        return re.compile(pattern, flags)\n")])
add("G6-02", "G6", "case_sensitive=True still ignores case", [(RX, "    flags = 0 if case_sensitive else re.IGNORECASE\n", "    flags = re.IGNORECASE\n")])
add("G6-03", "G6", "regex search ignores case_sensitive=False", [(RX, "regex_engine.IGNORECASE if flags else 0", "0")])
add("G6-04", "G6", "case_sensitive defaults to False", [(TL, 'case_sensitive=args.get("case_sensitive", True),', 'case_sensitive=args.get("case_sensitive", False),')])
add("G6-05", "G6", "reported line number is off by one", [(RX, '"line": index + 1,', '"line": index,')])
add("G6-06", "G6", "scan order ignores depth (shallow-first lost)", [(GR, "    return (depth, size is None, size or 0, file.id)\n", "    return (size is None, size or 0, file.id)\n")])
add("G6-07", "G6", "scan order has no id tie-break", [(GR, "    return (depth, size is None, size or 0, file.id)\n", "    return (depth, size is None, size or 0)\n")], sev="may", expect="survive")
add("G6-08", "G6", "scan order not sorted at all", [(GR, "    if not single_target:\n        files.sort(key=lambda item: _sort_key(item, walk.depths.get(item.id, 0)))\n", "    if False:\n        pass\n")])
add("G6-09", "G6", "listing order left to Drive (unspecified)", [(LS, "    return sorted(kept, key=lambda f: (f.is_folder, f.name.casefold(), f.name, f.id))\n", "    return kept\n")], sev="may")
add("G6-10", "G6", "a file with two parents is scanned twice", [(GR, "        if item.id not in seen:\n", "        if True:\n")])
add("G6-11", "G6", "a repeated id in file_ids is scanned twice", [(GR, "        file_ids = list(dict.fromkeys(file_ids))\n", "        file_ids = list(file_ids)\n")], expect="survive")
add("G6-12", "G6", "find name_pattern becomes case-sensitive", [(FD, "    if name_pattern and name_pattern.lower() not in file.name.lower():\n", "    if name_pattern and name_pattern not in file.name:\n")])

# ------------------------------------------------------- G7 ephemerality / isolation
MEMO = S + "infra/google_drive/memo.py"
add("G7-01", "G7", "the metadata memo is shared by every call (stale across requests)",
    [(MEMO, "class MemoDrive:\n", "_SHARED: dict = {}\n\n\nclass MemoDrive:\n"), (MEMO, "        self._metadata: dict[str, dict] = {}\n", "        self._metadata = _SHARED\n")],
    killer="tests/contract/test_one_metadata_get_per_id.py::test_the_memo_lasts_one_call")
add("G7-02", "G7", "the memo hands out its own dict (a caller can change what others see)", [(MEMO, "        return dict(hit)\n", "        return hit\n")], sev="should")
add("G7-03", "G7", "drive_read keeps the first text it saw per file id (stale after an edit)",
    [(RD, "MAX_WIRE_BYTES = 30 * 1024 * 1024\n", "_CACHE: dict = {}\nMAX_WIRE_BYTES = 30 * 1024 * 1024\n"),
     (RD, "    text, truncated = exported.text, exported.truncated\n", "    _CACHE.setdefault(file_id, exported)\n    exported = _CACHE[file_id]\n    text, truncated = exported.text, exported.truncated\n")])
add("G7-04", "G7", "drive_read writes the document text to disk",
    [(RD, "    budget.note_bytes(len(text.encode(\"utf-8\")))\n", "    budget.note_bytes(len(text.encode(\"utf-8\")))\n    open('/tmp/kb-copy-' + file_id, 'w').write(text)\n")])
add("G7-05", "G7", "a request's Drive binding is not cleared at the start of the next request", [(SV, "        reset_request_drive()\n        scid = None\n", "        scid = None\n")])
add("G7-06", "G7", "Google credentials are minted once and shared by every request",
    [(S + "infra/google_auth/refresh_token.py", "def mint_readonly_credentials(settings: Settings) -> Credentials:\n", "_CACHED = None\n\n\ndef mint_readonly_credentials(settings: Settings) -> Credentials:\n"),
     (S + "infra/google_auth/refresh_token.py", "    creds._mcp_request_key = str(uuid.uuid4())  # type: ignore[attr-defined]\n    _request_credentials.set(creds)\n    return creds\n",
      "    global _CACHED\n    if _CACHED is not None:\n        _request_credentials.set(_CACHED)\n        return _CACHED\n    creds._mcp_request_key = str(uuid.uuid4())  # type: ignore[attr-defined]\n    _CACHED = creds\n    _request_credentials.set(creds)\n    return creds\n")])
add("G7-07", "G7", "Google credentials mint skipped by reusing the previous request's binding", [(MW, "        _request_drive.set(drive)\n        return drive\n", "        _request_drive.set(_request_drive.get() or drive)\n        return _request_drive.get()\n")])

# ------------------------------------------------------------- G8 provenance / citation
TS = S + "mcp/tool_schema.py"
MA = S + "domain/matches.py"
add("G8-01", "G8", "the citation rule is dropped from every tool description", [(TS, 'def _describe(purpose: str, body: str) -> str:\n    """The tool\'s one-line purpose, then the citation rule, then the details."""\n    return f"{purpose}\\n\\n{CITING_RULE}\\n\\n{body}"\n',
                                                                 'def _describe(purpose: str, body: str) -> str:\n    """The tool\'s one-line purpose, then the citation rule, then the details."""\n    return f"{purpose}\\n\\n{body}"\n')])
add("G8-02", "G8", "the cited line says something else (tool descriptions)", [(TS, 'exactly one line: Source: onto-kb connector. "', 'exactly one line: Source: Google Drive. "')])
add("G8-03", "G8", "the cited line says something else (initialize instructions)", [(TS, "at the end of the answer: Source: onto-kb connector\n", "at the end of the answer: Source: Google Drive\n")])
add("G8-04", "G8", "'no Sources or References section' dropped from the instructions", [(TS, "That line is the only source you name. Do not add a Sources or References section.", "That line is the only source you name.")])
add("G8-05", "G8", "'no Sources section, no file names or ids' dropped from every tool description",
    [(TS, '    "Name no other source: no Sources or References section, and never list, number "\n    "or link file names or ids; they are for your own tracking. One exception: a "\n', '    "One exception: a "\n')])
add("G8-06", "G8", "grep matches carry a source locator again", [(MA, '            "location": self.location,\n        }\n', '            "location": self.location,\n            "source_url": "drive:" + self.file_id,\n        }\n')])
add("G8-07", "G8", "ls children carry the Drive link again", [(S + "domain/drive_file.py", '            "is_folder": self.is_folder,\n            "modified_time": self.modified_time,\n        }\n', '            "is_folder": self.is_folder,\n            "modified_time": self.modified_time,\n            "web_view_link": self.web_view_link,\n        }\n')])
add("G8-08", "G8", "grep matches lose retrieved_at", [(MA, '            "retrieved_at": self.retrieved_at,\n', "")])
add("G8-09", "G8", "grep matches lose modified_time", [(MA, '            "modified_time": self.modified_time,\n', "")])
add("G8-10", "G8", "grep matches lose their location (line/offset)", [(MA, '            "location": self.location,\n', "")])
add("G8-11", "G8", "drive_read loses modified_time", [(RD, '        "modified_time": meta.modified_time,\n', "")])
add("G8-12", "G8", "drive_read loses retrieved_at", [(RD, '        "retrieved_at": retrieved_at,\n', "")])
add("G8-13", "G8", "tool descriptions grow past the length hosts clip at (rule can be cut off)", [(TS, '    "Stack Exchange link beside text quoted word for word from Stack Exchange."\n)', '    "Stack Exchange link beside text quoted word for word from Stack Exchange." + " pad" * 1000\n)')])

# ----------------------------------------------------------------- G9 failure taxonomy
GE = S + "domain/google_errors.py"
add("G9-01", "G9", "403 no longer reads as FILE_NOT_FOUND (permission and absence become distinguishable)", [(GE, "    if status in (404, 403):\n", "    if status in (404,):\n")])
add("G9-02", "G9", "429 no longer reads as RATE_LIMITED", [(GE, "    if status == 429:\n", "    if status == 503:\n")])
add("G9-03", "G9", "an unexpected Drive error reads as FILE_NOT_FOUND", [(GE, "    return envelope(ErrorCategory.DRIVE_API_ERROR, request_id=request_id)\n", "    return envelope(ErrorCategory.FILE_NOT_FOUND, request_id=request_id)\n")])
add("G9-04", "G9", "an unsupported type reads as INVALID_ARGUMENT", [(S + "infra/google_drive/export.py", "        if default is None:\n            raise DomainError.of(ErrorCategory.UNSUPPORTED_MIME_TYPE)\n        return default\n", "        if default is None:\n            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)\n        return default\n")], sev="should")
add("G9-05", "G9", "a binary file is downloaded and decoded as text", [(S + "infra/google_drive/export.py", "    if not is_workspace(mime_type) and not is_text_blob(mime_type, name):\n        raise DomainError.of(ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id)\n", "    if False:\n        pass\n")])
add("G9-06", "G9", "arguments a tool does not take are accepted (chain and tool see different scopes)", [(TL, "        if known is None or not supplied <= known:\n", "        if known is None:\n")])
add("G9-07", "G9", "decision envelope carries the internal reason code in its message",
    [(S + "access_control/decisions.py", "        return envelope(ErrorCategory(self.outcome.value), request_id=request_id)\n", "        return envelope(ErrorCategory(self.outcome.value), message=self.reason_code, request_id=request_id)\n")], sev="should")

# ------------------------------------------------------------------ G10 secrets and logs
LG = S + "infra/logging.py"
add("G10-01", "G10", "a 'content' field is allowed into log records", [(LG, '_FIELDS = (\n    "request_id",\n', '_FIELDS = (\n    "content",\n    "authorization",\n    "request_id",\n')])
add("G10-02", "G10", "bearer tokens are no longer redacted", [(LG, '    out = _BEARER_RE.sub("Bearer [REDACTED]", text)\n', "    out = text\n")])
add("G10-03", "G10", "Authorization headers are no longer redacted", [(LG, '    out = _AUTH_HEADER_RE.sub("Authorization: [REDACTED]", out)\n', "    out = out\n")])
add("G10-04", "G10", "log lines carry exception text, not just the type", [(LG, '            entry["exception"] = record.exc_info[0].__name__\n', '            entry["exception"] = str(record.exc_info[1])\n')])
add("G10-05", "G10", "httpx request URLs are logged at INFO (carry keys and emails)", [(LG, "        logging.getLogger(name).setLevel(logging.WARNING)\n", "        logging.getLogger(name).setLevel(logging.INFO)\n")])
add("G10-06", "G10", "log message text is not redacted", [(LG, '            "message": redact(record.getMessage()),\n', '            "message": record.getMessage(),\n')])
add("G10-07", "G10", "string fields are not redacted", [(LG, "            entry[key] = redact(value) if isinstance(value, str) else value\n", "            entry[key] = value\n")])

# ---------------------------------------------------------------------- G11 abuse limits
BG = S + "domain/budgets.py"
VA = S + "mcp/validation.py"
LM = S + "mcp/limits.py"
add("G11-01", "G11", "grep file cap 200 -> 2000", [(BG, "GREP_MAX_FILES = 200\n", "GREP_MAX_FILES = 2000\n")])
add("G11-02", "G11", "ls/find file cap 40 -> 400", [(BG, "MAX_FILES = 40\n", "MAX_FILES = 400\n")])
add("G11-03", "G11", "match cap 50 -> 5000", [(BG, "MAX_MATCHES = 50\n", "MAX_MATCHES = 5000\n")])
add("G11-04", "G11", "per-operation byte cap 20 MB -> 200 MB", [(BG, "MAX_BYTES_PER_OPERATION = 20_000_000\n", "MAX_BYTES_PER_OPERATION = 200_000_000\n")])
add("G11-05", "G11", "per-file byte cap 20 MB -> 200 MB", [(BG, "MAX_BYTES_PER_FILE = 20_000_000\n", "MAX_BYTES_PER_FILE = 200_000_000\n")])
add("G11-06", "G11", "export size cap 20 MB -> 200 MB", [(BG, "MAX_EXPORT_SIZE = 20_000_000\n", "MAX_EXPORT_SIZE = 200_000_000\n")])
add("G11-07", "G11", "time cap 25 s -> 250 s", [(BG, "MAX_EXECUTION_TIME = 25.0\n", "MAX_EXECUTION_TIME = 250.0\n")])
add("G11-08", "G11", "the caller's max_matches can raise the cap above 50", [(GR, "        budget.max_matches = min(budget.max_matches, max_matches)\n", "        budget.max_matches = max_matches\n")])
add("G11-09", "G11", "the caller's max_results can raise the find cap above 40", [(FD, "        budget.max_files = min(budget.max_files, max_results)\n", "        budget.max_files = max_results\n")])
add("G11-10", "G11", "validation: max_results ceiling 40 -> 4000", [(VA, "MAX_RESULTS_MAX = 40\n", "MAX_RESULTS_MAX = 4000\n")])
add("G11-11", "G11", "validation: max_matches ceiling 50 -> 5000", [(VA, "MAX_MATCHES_MAX = 50\n", "MAX_MATCHES_MAX = 5000\n")])
add("G11-12", "G11", "validation: max_bytes ceiling 20 MB -> 200 MB", [(VA, "MAX_BYTES_MAX = 20_000_000\n", "MAX_BYTES_MAX = 200_000_000\n")])
add("G11-13", "G11", "grep never charges the byte budget", [(GR, "            budget.note_bytes(\n                size if size is not None and not exported.truncated else exported.byte_length\n            )\n", "            pass\n")])
add("G11-14", "G11", "grep returns more matches than max_matches from one file", [(GR, "            raw = raw[:match_room]\n", "            raw = raw\n")])
add("G11-15", "G11", "grep file cap not enforced", [(GR, "            if files_scanned >= budget.max_files:\n", "            if False:\n")])
add("G11-16", "G11", "prefetch fetches a file that does not fit the remaining bytes", [(GR, "            if room <= 0 or size is None or size > self._max_file_bytes or size > room:\n", "            if room <= 0 or size is None or size > self._max_file_bytes:\n")])
add("G11-17", "G11", "read wire cap 30 MiB -> 300 MiB (Cloud Run rejects >32 MiB)", [(RD, "MAX_WIRE_BYTES = 30 * 1024 * 1024\n", "MAX_WIRE_BYTES = 300 * 1024 * 1024\n")])
add("G11-18", "G11", "/mcp body cap 4 MiB -> 400 MiB", [(LM, "MCP_BODY_LIMIT = 4 * 1024 * 1024\n", "MCP_BODY_LIMIT = 400 * 1024 * 1024\n")])
add("G11-19", "G11", "/register rate limit 20/h -> 20000/h", [(LM, '    ("POST", "/register"): (20, 3600),\n', '    ("POST", "/register"): (20000, 3600),\n')])
add("G11-20", "G11", "/token rate limit 600/min -> 600000/min", [(LM, '    ("POST", "/token"): (600, 60),\n', '    ("POST", "/token"): (600000, 60),\n')])
add("G11-21", "G11", "prefetch byte window 8 MB -> 800 MB", [(BG, "GREP_PREFETCH_WINDOW_BYTES = 8_000_000\n", "GREP_PREFETCH_WINDOW_BYTES = 800_000_000\n")])

# ----------------------------------------------------------- G12 documents are data
add("G12-01", "G12", "document text is passed to exec() (executable documents)",
    [(RD, "    text, truncated = exported.text, exported.truncated\n", "    text, truncated = exported.text, exported.truncated\n    if text.startswith('#!run:'):\n        exec(text[6:])\n")])
add("G12-02", "G12", "document text is handed to a shell",
    [(RD, "    text, truncated = exported.text, exported.truncated\n", "    text, truncated = exported.text, exported.truncated\n    if text.startswith('#!sh:'):\n        __import__('subprocess').run(text[5:], shell=True)\n")])
add("G12-03", "G12", "document text is used as the next tool call (server follows instructions in a document)",
    [(RD, "    text, truncated = exported.text, exported.truncated\n", "    text, truncated = exported.text, exported.truncated\n    if text.startswith('#!next:'):\n        return drive_read(drive, file_id=text[7:].split()[0])\n")])

# --------------------------------------------------------------------------- G13 speed
add("G13-01", "G13", "no per-call memo: the tool asks Drive for each id again", [(MW, "        drive = MemoDrive(client)\n", "        drive = client\n")], sev="may")
add("G13-02", "G13", "the id lookups run one after another", [(CH, "concurrent=needs_tree) as fetching:", "concurrent=False) as fetching:")], sev="may")
add("G13-03", "G13", "the token is fetched by every thread (no lock)", [(CL, "        with self._auth_lock:\n", "        if True:\n")], sev="may")
add("G13-04", "G13", "folders are listed one at a time", [(BG, "LIST_WORKERS = 8\n", "LIST_WORKERS = 1\n")], sev="may")
add("G13-05", "G13", "downloads run one at a time", [(BG, "GREP_PREFETCH_WORKERS = 16\n", "GREP_PREFETCH_WORKERS = 1\n")], sev="may")
add("G13-06", "G13", "id lookup pool shrinks to one worker", [(CH, "FETCH_WORKERS = 8\n", "FETCH_WORKERS = 1\n")], sev="may")

# ----------------------------------------------------------- G14 OAuth and identity surface
CM = S + "infra/mcp_auth/cimd.py"
DC = S + "infra/mcp_auth/dcr.py"
CS = S + "infra/mcp_auth/consent.py"
PV = S + "infra/mcp_auth/provider.py"
EN = S + "infra/billing/entitlement.py"
EL = S + "infra/billing/email_link.py"
SV = S + "mcp/server.py"

add("G14-01", "G14", "client-metadata fetch: the host allow-list is dropped (SSRF via client_id)",
    [(CM, '    return parsed.scheme == "https" and host in ALLOWED_CIMD_HOSTS and bool(parsed.path)\n',
      '    return parsed.scheme == "https" and bool(parsed.path)\n')])
add("G14-02", "G14", "client-metadata fetch: host matched by prefix (https://claude.ai.evil.example/x passes)",
    [(CM, '    return parsed.scheme == "https" and host in ALLOWED_CIMD_HOSTS and bool(parsed.path)\n',
      '    return client_id.startswith(("https://claude.ai", "https://chatgpt.com", "https://claude.com")) and bool(parsed.path)\n')])
add("G14-03", "G14", "client-metadata fetch follows redirects (an allowed host can bounce it inward)",
    [(CM, "follow_redirects=False", "follow_redirects=True")])
add("G14-04", "G14", "client_id length cap removed", [(CM, "    if len(client_id) > MAX_CLIENT_ID:\n        return False\n", "    if False:\n        return False\n")], sev="should")
add("G14-05", "G14", "redirect allow-list defaults to allow (authorization code can go to any URL)",
    [(CM, '        return path == "/callback" or path.startswith("/callback/")\n    return False\n',
      '        return path == "/callback" or path.startswith("/callback/")\n    return True\n')])
add("G14-06", "G14", "plain-http redirect accepted for any host, not only loopback",
    [(CM, '    if parsed.scheme == "http" and host in _LOOPBACK_HOSTS:\n', '    if parsed.scheme == "http":\n')])
add("G14-07", "G14", "registered client id: token type not checked (any signed token is a client)",
    [(DC, "    if claims is None or claims.get(\"typ\") != TYP_DCR:\n        return None\n", "    if claims is None:\n        return None\n")])
add("G14-08", "G14", "registered client id: audience not checked",
    [(DC, "    if claims.get(\"aud\") != issuer_url(settings):\n        return None\n", "    if False:\n        return None\n")])
add("G14-09", "G14", "registration: redirect_uris ceiling 5 -> 5000", [(DC, "MAX_REDIRECT_URIS = 5\n", "MAX_REDIRECT_URIS = 5000\n")], sev="should")
add("G14-10", "G14", "registration: metadata ceiling 16 KB -> 16 MB", [(DC, "MAX_METADATA_BYTES = 16 * 1024\n", "MAX_METADATA_BYTES = 16 * 1024 * 1024\n")], sev="should")
add("G14-11", "G14", "consent: the password is not checked",
    [(CS, '        if not verify_bearer(password, expected):\n            return _password_page(ticket, error="Incorrect password.")\n',
      '        if False:\n            return _password_page(ticket, error="Incorrect password.")\n')])
add("G14-12", "G14", "consent: a lapsed subscriber's click still issues a code",
    [(CS, "        if scid is None or not await provider._active(scid):\n", "        if scid is None:\n")])
add("G14-13", "G14", "consent page: client_name not HTML-escaped (script injection from a registered name)",
    [(CS, "            client_name=html.escape(name),\n", "            client_name=name,\n")])
add("G14-14", "G14", "consent page: return host not HTML-escaped", [(CS, "            return_host=html.escape(host),\n", "            return_host=host,\n")])
add("G14-15", "G14", "consent page: ticket not HTML-escaped", [(CS, "            ticket=html.escape(ticket, quote=True),\n", "            ticket=ticket,\n")])
add("G14-16", "G14", "consent: the click is no longer tied to the subscriber's own browser (hash not compared)",
    [(PV, "        if not hmac.compare_digest(subscriber_hash(self.settings, scid), expected):\n            return None\n",
      "        if False:\n            return None\n")])
add("G14-17", "G14", "an authorization code works for a different client",
    [(PV, "        if claims.get(\"client_id\") != client.client_id:\n            return None\n        return AuthorizationCode(",
      "        return AuthorizationCode(")])
add("G14-18", "G14", "a refresh token works for a different client",
    [(PV, "        if claims.get(\"client_id\") != client.client_id:\n            return None\n        return RefreshToken(",
      "        return RefreshToken(")])
add("G14-19", "G14", "resume redirect: only /authorize paths allowed check dropped (open redirect)",
    [(EN, '    if value != "/authorize" and not value.startswith("/authorize?"):\n        return None\n', "    if False:\n        return None\n")])
add("G14-20", "G14", "resume redirect: '//', '://' and backslash checks dropped",
    [(EN, '    if "\\\\" in value or "://" in value or value.startswith("//"):\n        return None\n', "    if False:\n        return None\n")])
add("G14-21", "G14", "email restore: the link's address need not match the typed address (account takeover)",
    [(EL, "        if not verified or verified != email.strip().lower():\n            return None\n", "        if not verified:\n            return None\n")])
add("G14-22", "G14", "email restore: the address is left on the identity provider's side",
    [(EL, '            self._post("accounts:delete", {"idToken": id_token})\n', "            pass\n")], sev="should")
add("G14-23", "G14", "resume cookie loses HttpOnly",
    [(SV, "; HttpOnly; Path=/; \"\n                        f\"Max-Age=3600; SameSite=Lax\"", "; Path=/; \"\n                        f\"Max-Age=3600; SameSite=Lax\"")], sev="should")

# --------------------------------------------------------------------- second-order entries
# Two redundant layers removed together. Each layer alone survives by design (the notes below);
# removing both must be killed (G6-S1, G1-S1), unless a third layer still holds (G1-S2, G1-S3).
_by = {m.id: m for m in MUTANTS}
add("G6-S1", "G6", "second order: both duplicate guards removed (two-parent scan and repeated file_ids)",
    _by["G6-10"].edits + _by["G6-11"].edits)
add("G1-S1", "G1", "second order: the two layers that rewrite the tool's own arguments removed together",
    _by["G1-09"].edits + _by["G1-10"].edits)
add("G1-S2", "G1", "second order: rewrite layers 2 and 3 removed together (layer 1 still rewrites the arguments)",
    _by["G1-10"].edits + _by["G1-11"].edits, expect="survive")
add("G1-S3", "G1", "second order: rewrite layers 1 and 3 removed together (layer 2 still rewrites the arguments)",
    _by["G1-09"].edits + _by["G1-11"].edits, expect="survive")

# ------------------------------------------------------------ why the survivors are not gaps
SURVIVOR_NOTES = {

    "G1-09": "equivalent while the other argument-rewriting layer holds; both together are killed (G1-S1)",
    "G1-10": "equivalent while the other argument-rewriting layer holds; both together are killed (G1-S1)",
    "G1-11": "equivalent: the chain's own rewrite only feeds its decision, and the arguments arrive already rewritten",
    "G1-13": "unreachable while any rewrite layer holds: the folder is always set before this check",
    "G1-18": "equivalent: the chain checks the same membership first",
    "G1-S2": "one argument-rewriting layer still holds",
    "G1-S3": "one argument-rewriting layer still holds",
    "G5-05": "dead code: a cut listing returns earlier, so walk.time_exceeded is always false at this point",
    "G5-18": "redundant: immediate_children sets truncated equal to more, so the second test never differs",
    "G6-07": "not a requirement: equal-sized files are ordered by name or by id, both deterministic; the contract does not say which",
    "G6-11": "masked by the second duplicate guard; both removed together is killed (G6-S1)",
}
for _m in MUTANTS:
    if _m.expect == "survive":
        _m.note = SURVIVOR_NOTES[_m.id]
