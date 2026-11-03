<%@ page language="java" contentType="application/json; charset=utf-8" import="java.util.*,us.mn.state.health.lims.hibernate.HibernateUtil,org.hibernate.*,org.json.*,java.io.*"%><%
    response.setHeader("Cache-Control", "no-cache");
    StringBuilder bodyBuilder = new StringBuilder();
    BufferedReader reader = request.getReader();
    String line;
    while ((line = reader.readLine()) != null) bodyBuilder.append(line);
    String rawBody = bodyBuilder.toString().trim();
    JSONObject json = null;
    if (!rawBody.isEmpty() && rawBody.startsWith("{")) {
        try {
            json = new JSONObject(rawBody);
        } catch (Exception ignore) {}
    }
    if (json == null) json = new JSONObject();

    String orderId = json.optString("orderId", "").trim();
    if (orderId.isEmpty()) {
        orderId = request.getParameter("orderId");
        if (orderId == null) orderId = "";
        orderId = orderId.trim();
    }
    if (orderId.isEmpty()) {
        out.print("{\"success\":false,\"error\":\"orderId is required\"}");
        return;
    }

    JSONArray selections = null;
    Object selObj = json.opt("selections");
    if (selObj instanceof JSONArray) {
        selections = (JSONArray) selObj;
    } else if (selObj instanceof String) {
        String selStr = ((String) selObj).trim();
        if (!selStr.isEmpty()) {
            try {
                selections = new JSONArray(selStr);
            } catch (Exception ignore) {}
        }
    }
    if (selections == null) {
        String selParam = request.getParameter("selections");
        if (selParam != null && !selParam.trim().isEmpty()) {
            try {
                selections = new JSONArray(selParam.trim());
            } catch (Exception ignore) {}
        }
    }
    if (selections == null || selections.length() == 0) {
        out.print("{\"success\":false,\"error\":\"No tests provided in selections payload\"}");
        return;
    }

    Session hSession = null;
    Transaction tx = null;
    List<String> stockOutNames = new ArrayList<String>();
    List<String> stockOutUuids = new ArrayList<String>();
    List<String> availableNames = new ArrayList<String>();
    List<String> availableUuids = new ArrayList<String>();
    String patientRef = "";

    try {
        hSession = HibernateUtil.getSession();
        tx = hSession.beginTransaction();

        java.math.BigDecimal sid = new java.math.BigDecimal(orderId);
        java.math.BigDecimal csid = sid;
        try {
            List sCheck = hSession.createSQLQuery("SELECT id FROM sample WHERE id = :sid").setParameter("sid", sid).list();
            if (sCheck == null || sCheck.isEmpty()) {
                List shRows = hSession.createSQLQuery("SELECT samp_id FROM sample_human WHERE id = :sid").setParameter("sid", sid).list();
                if (shRows != null && !shRows.isEmpty() && shRows.get(0) != null) {
                    csid = new java.math.BigDecimal(shRows.get(0).toString().trim());
                }
            }
        } catch (Exception ignore) {}

        // Get patient identifier (ST number) for Odoo sync
        try {
            org.hibernate.Query pRows = hSession.createSQLQuery(
                "SELECT pi.identity_data FROM sample_human sh " +
                "JOIN patient_identity pi ON sh.patient_id = pi.patient_id " +
                "JOIN patient_identity_type pit ON pi.identity_type_id = pit.id " +
                "WHERE (sh.samp_id = :csid OR sh.id = :csid) AND pit.identity_type IN ('ST', 'NATIONAL', 'SUBJECT') " +
                "ORDER BY CASE WHEN pit.identity_type = 'ST' THEN 1 WHEN pit.identity_type = 'NATIONAL' THEN 2 ELSE 3 END " +
                "LIMIT 1"
            );
            pRows.setParameter("csid", csid);
            List pResults = pRows.list();
            if (pResults != null && !pResults.isEmpty() && pResults.get(0) != null) {
                patientRef = pResults.get(0).toString().trim();
            }
        } catch (Exception ignore) {}

        if (patientRef.isEmpty()) {
            try {
                org.hibernate.Query pQuery = hSession.createSQLQuery(
                    "SELECT pi.identity_data FROM sample_human sh " +
                    "JOIN patient_identity pi ON sh.patient_id = pi.patient_id " +
                    "WHERE (sh.samp_id = :csid OR sh.id = :csid) AND pi.identity_data IS NOT NULL AND TRIM(pi.identity_data) != '' " +
                    "ORDER BY LENGTH(pi.identity_data) ASC LIMIT 1"
                );
                pQuery.setParameter("csid", csid);
                List pResults = pQuery.list();
                if (pResults != null && !pResults.isEmpty() && pResults.get(0) != null) {
                    patientRef = pResults.get(0).toString().trim();
                }
            } catch (Exception ignore) {}
        }

        String sampleUuid = "";
        try {
            org.hibernate.Query uQuery = hSession.createSQLQuery("SELECT uuid FROM sample WHERE id = :csid LIMIT 1")
                .setParameter("csid", csid);
            List uRows = uQuery.list();
            if (uRows != null && !uRows.isEmpty() && uRows.get(0) != null) {
                sampleUuid = uRows.get(0).toString().trim();
            }
        } catch (Exception ignore) {}

        // Delete any existing entries for csid and sid to ensure clean state
        hSession.createSQLQuery("DELETE FROM stock_out_selection WHERE sample_id = :csid OR sample_id = :sid")
            .setParameter("csid", csid)
            .setParameter("sid", sid)
            .executeUpdate();

        boolean confirmNow = json.optBoolean("confirmNow", false);
        if (selections != null) {
            for (int i = 0; i < selections.length(); i++) {
                JSONObject s = selections.getJSONObject(i);
                int tid = s.optInt("testId", 0);
                String tn = s.optString("testName", "").trim();
                String st = s.optString("status", "available").trim();
                if (!"stockout".equalsIgnoreCase(st)) {
                    st = confirmNow ? "confirmed" : "available";
                }
                String conceptUuid = s.optString("conceptUuid", "").trim();

                // If testId is missing, look up from test table
                if (tid == 0 && !tn.isEmpty()) {
                    try {
                        List tRows = hSession.createSQLQuery("SELECT id FROM test WHERE LOWER(name) = :tn OR LOWER(description) = :tn LIMIT 1")
                            .setParameter("tn", tn.toLowerCase()).list();
                        if (tRows != null && !tRows.isEmpty() && tRows.get(0) != null) {
                            tid = ((Number) tRows.get(0)).intValue();
                        }
                    } catch (Exception ignore) {}
                }

                // If conceptUuid is missing, look up from external_reference
                if (conceptUuid.isEmpty() && tid > 0) {
                    try {
                        List uRows = hSession.createSQLQuery("SELECT external_id FROM external_reference WHERE item_id = :tid AND type = 'Test' LIMIT 1")
                            .setParameter("tid", tid).list();
                        if (uRows != null && !uRows.isEmpty() && uRows.get(0) != null) {
                            conceptUuid = uRows.get(0).toString().trim();
                        }
                    } catch (Exception ignore) {}
                }

                if ("stockout".equalsIgnoreCase(st)) {
                    stockOutNames.add(tn);
                    if (!conceptUuid.isEmpty()) stockOutUuids.add(conceptUuid);
                } else {
                    availableNames.add(tn);
                    if (!conceptUuid.isEmpty()) availableUuids.add(conceptUuid);
                }

                hSession.createSQLQuery("INSERT INTO stock_out_selection (sample_id, test_id, test_name, status, concept_uuid, sent_to_billing, created_at, updated_at) VALUES (:csid, :tid, :tn, :st, :cu, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
                    .setParameter("csid", csid)
                    .setParameter("tid", tid)
                    .setParameter("tn", tn)
                    .setParameter("st", st)
                    .setParameter("cu", conceptUuid)
                    .executeUpdate();

                if (!sid.equals(csid)) {
                    hSession.createSQLQuery("INSERT INTO stock_out_selection (sample_id, test_id, test_name, status, concept_uuid, sent_to_billing, created_at, updated_at) VALUES (:sid, :tid, :tn, :st, :cu, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
                        .setParameter("sid", sid)
                        .setParameter("tid", tid)
                        .setParameter("tn", tn)
                        .setParameter("st", st)
                        .setParameter("cu", conceptUuid)
                        .executeUpdate();
                }
            }
        }

        tx.commit();

        // Asynchronously execute background sync with Odoo and OpenMRS so the HTTP response is instantaneous (<50ms)
        final List<String> fStockOutNames = new ArrayList<String>(stockOutNames);
        final List<String> fStockOutUuids = new ArrayList<String>(stockOutUuids);
        final List<String> fAvailableNames = new ArrayList<String>(availableNames);
        final List<String> fAvailableUuids = new ArrayList<String>(availableUuids);
        final String fPatientRef = patientRef;
        final String fSampleUuid = sampleUuid;

        new Thread(new Runnable() {
            public void run() {
                try {
                    // 1. Protect billing in Odoo: cancel/unlink stock-out lines AND void in OpenMRS
                    if (!fStockOutNames.isEmpty() && !fPatientRef.isEmpty()) {
                        try {
                            StringBuilder pyCmd = new StringBuilder();
                            pyCmd.append("import xmlrpclib, urllib2, base64, json\n");
                            pyCmd.append("common = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/common')\n");
                            pyCmd.append("uid = common.authenticate('odoo', 'emrsync', 'Admin123', {})\n");
                            pyCmd.append("pwd = 'Admin123'\n");
                            pyCmd.append("if not uid:\n");
                            pyCmd.append("    uid = common.authenticate('odoo', 'admin', 'admin', {})\n");
                            pyCmd.append("    pwd = 'admin'\n");
                            pyCmd.append("if uid:\n");
                            pyCmd.append("    models = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/object')\n");
                            pyCmd.append("    models.execute_kw('odoo', uid, pwd, 'api.event.worker', 'process_event', [{\n");
                            pyCmd.append("        'category': 'cancel.order',\n");
                            pyCmd.append("        'patientId': '").append(fPatientRef).append("',\n");
                            pyCmd.append("        'orderUuid': '").append(fSampleUuid).append("',\n");
                            pyCmd.append("        'stockOutTestNames': [");
                            for (int k = 0; k < fStockOutNames.size(); k++) {
                                if (k > 0) pyCmd.append(",");
                                pyCmd.append("'").append(fStockOutNames.get(k).replace("'", "\\'")).append("'");
                            }
                            pyCmd.append("],\n");
                            pyCmd.append("        'stockOutTestUuids': [");
                            for (int k = 0; k < fStockOutUuids.size(); k++) {
                                if (k > 0) pyCmd.append(",");
                                pyCmd.append("'").append(fStockOutUuids.get(k).replace("'", "\\'")).append("'");
                            }
                            pyCmd.append("]\n");
                            pyCmd.append("    }])\n");

                            // Void matching active orders in OpenMRS
                            pyCmd.append("try:\n");
                            pyCmd.append("    p_req = urllib2.Request('http://openmrs:8080/openmrs/ws/rest/v1/patient?q=").append(fPatientRef).append("&v=default')\n");
                            pyCmd.append("    p_req.add_header('Authorization', 'Basic ' + base64.b64encode('admin:Admin123'))\n");
                            pyCmd.append("    p_res = urllib2.urlopen(p_req)\n");
                            pyCmd.append("    p_data = json.loads(p_res.read())\n");
                            pyCmd.append("    if p_data.get('results'):\n");
                            pyCmd.append("        p_uuid = p_data['results'][0]['uuid']\n");
                            pyCmd.append("        o_req = urllib2.Request('http://openmrs:8080/openmrs/ws/rest/v1/order?patient=' + p_uuid + '&v=full')\n");
                            pyCmd.append("        o_req.add_header('Authorization', 'Basic ' + base64.b64encode('admin:Admin123'))\n");
                            pyCmd.append("        o_res = urllib2.urlopen(o_req)\n");
                            pyCmd.append("        orders_data = json.loads(o_res.read())\n");
                            pyCmd.append("        opener = urllib2.build_opener(urllib2.HTTPHandler)\n");
                            pyCmd.append("        so_list = [");
                            for (int k = 0; k < fStockOutNames.size(); k++) {
                                if (k > 0) pyCmd.append(",");
                                pyCmd.append("'").append(fStockOutNames.get(k).replace("'", "\\'").toLowerCase()).append("'");
                            }
                            pyCmd.append("]\n");
                            pyCmd.append("        for ord_item in orders_data.get('results', []):\n");
                            pyCmd.append("            disp = (ord_item.get('concept', {}).get('display') or '').strip().lower()\n");
                            pyCmd.append("            ouuid = ord_item.get('uuid')\n");
                            pyCmd.append("            for s_name in so_list:\n");
                            pyCmd.append("                if s_name in disp or disp in s_name or (s_name == 'rbs' and 'random blood sugar' in disp):\n");
                            pyCmd.append("                    v_req = urllib2.Request('http://openmrs:8080/openmrs/ws/rest/v1/order/' + ouuid + '?reason=Reagent+Out+of+Stock')\n");
                            pyCmd.append("                    v_req.get_method = lambda: 'DELETE'\n");
                            pyCmd.append("                    v_req.add_header('Authorization', 'Basic ' + base64.b64encode('admin:Admin123'))\n");
                            pyCmd.append("                    try:\n");
                            pyCmd.append("                        opener.open(v_req)\n");
                            pyCmd.append("                    except Exception:\n");
                            pyCmd.append("                        pass\n");
                            pyCmd.append("                    break\n");
                            pyCmd.append("except Exception:\n");
                            pyCmd.append("    pass\n");

                            ProcessBuilder pb = new ProcessBuilder("python", "-c", pyCmd.toString());
                            pb.redirectErrorStream(true);
                            Process proc = pb.start();
                            proc.waitFor();
                        } catch (Exception ignore) {}
                    }

                    // 2. Add evaluated and confirmed AVAILABLE tests to Odoo for billing
                    if (!fAvailableNames.isEmpty() && !fPatientRef.isEmpty()) {
                        try {
                            StringBuilder pyCmd = new StringBuilder();
                            pyCmd.append("import xmlrpclib\n");
                            pyCmd.append("common = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/common')\n");
                            pyCmd.append("uid = common.authenticate('odoo', 'emrsync', 'Admin123', {})\n");
                            pyCmd.append("pwd = 'Admin123'\n");
                            pyCmd.append("if not uid:\n");
                            pyCmd.append("    uid = common.authenticate('odoo', 'admin', 'admin', {})\n");
                            pyCmd.append("    pwd = 'admin'\n");
                            pyCmd.append("if uid:\n");
                            pyCmd.append("    models = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/object')\n");
                            pyCmd.append("    models.execute_kw('odoo', uid, pwd, 'api.event.worker', 'process_event', [{\n");
                            pyCmd.append("        'category': 'add.available.lab.tests',\n");
                            pyCmd.append("        'patientId': '").append(fPatientRef).append("',\n");
                            pyCmd.append("        'orderUuid': '").append(fSampleUuid).append("',\n");
                            pyCmd.append("        'availableTestNames': [");
                            for (int k = 0; k < fAvailableNames.size(); k++) {
                                if (k > 0) pyCmd.append(",");
                                pyCmd.append("'").append(fAvailableNames.get(k).replace("'", "\\'")).append("'");
                            }
                            pyCmd.append("],\n");
                            pyCmd.append("        'availableTestUuids': [");
                            for (int k = 0; k < fAvailableUuids.size(); k++) {
                                if (k > 0) pyCmd.append(",");
                                pyCmd.append("'").append(fAvailableUuids.get(k).replace("'", "\\'")).append("'");
                            }
                            pyCmd.append("]\n");
                            pyCmd.append("    }])\n");
                            if (confirmNow) {
                                pyCmd.append("    try:\n");
                                pyCmd.append("        models.execute_kw('odoo', uid, pwd, 'api.event.worker', 'process_event', [{\n");
                                pyCmd.append("            'category': 'confirm.sale.order',\n");
                                pyCmd.append("            'patientId': '").append(fPatientRef).append("',\n");
                                pyCmd.append("            'orderUuid': '").append(fSampleUuid).append("'\n");
                                pyCmd.append("        }])\n");
                                pyCmd.append("    except Exception:\n");
                                pyCmd.append("        pass\n");
                            }

                            ProcessBuilder pb = new ProcessBuilder("python", "-c", pyCmd.toString());
                            pb.redirectErrorStream(true);
                            Process proc = pb.start();
                            proc.waitFor();
                        } catch (Exception ignore) {}
                    }
                } catch (Exception ignore) {}
            }
        }).start();

        out.print("{\"success\":true,\"patientRef\":\"" + patientRef + "\",\"stockOutCount\":" + stockOutNames.size() + ",\"availableCount\":" + availableNames.size() + ",\"isSent\":true,\"confirmed\":" + confirmNow + "}");
    } catch (Exception e) {
        if (tx != null) try { tx.rollback(); } catch (Exception ex) {}
        String msg = e.getMessage() != null ? e.getMessage().replace("\"", "\\\"").replace("\n", " ") : "unknown error";
        out.print("{\"success\":false,\"error\":\"" + msg + "\"}");
    } finally {
        try {
            HibernateUtil.closeSession();
        } catch (Exception ignore) {}
    }
%>