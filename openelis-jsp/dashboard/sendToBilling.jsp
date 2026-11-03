<%@ page language="java" contentType="application/json; charset=utf-8" import="java.util.*,us.mn.state.health.lims.hibernate.HibernateUtil,org.hibernate.*,org.json.*,java.io.*"%><%
    response.setHeader("Cache-Control", "no-cache");
    String action = request.getParameter("action");
    String orderId = request.getParameter("orderId");
    String patientId = request.getParameter("patientId");

    // =========================================================================
    // 1. ACTION: CHECK ODOO CONFIRMED SALE ORDERS
    // =========================================================================
    if ("checkOdooConfirmed".equals(action)) {
        JSONArray pList = new JSONArray();
        try {
            StringBuilder pyCheck = new StringBuilder();
            pyCheck.append("import socket, xmlrpclib, json\n");
            pyCheck.append("socket.setdefaulttimeout(3.0)\n");
            pyCheck.append("try:\n");
            pyCheck.append("    common = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/common')\n");
            pyCheck.append("    uid = common.authenticate('odoo', 'emrsync', 'Admin123', {})\n");
            pyCheck.append("    pwd = 'Admin123'\n");
            pyCheck.append("    if not uid:\n");
            pyCheck.append("        uid = common.authenticate('odoo', 'admin', 'admin', {})\n");
            pyCheck.append("        pwd = 'admin'\n");
            pyCheck.append("    if uid:\n");
            pyCheck.append("        models = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/object')\n");
            pyCheck.append("        sos = models.execute_kw('odoo', uid, pwd, 'sale.order', 'search_read',\n");
            pyCheck.append("            [[['state', 'in', ['sale', 'done']]]],\n");
            pyCheck.append("            {'fields': ['id', 'name', 'partner_id', 'client_order_ref', 'origin'], 'limit': 200, 'order': 'id desc'})\n");
            pyCheck.append("        refs = []\n");
            pyCheck.append("        for so in sos:\n");
            pyCheck.append("            p = so.get('partner_id')\n");
            pyCheck.append("            if p and len(p) > 1 and isinstance(p[1], (str, unicode)):\n");
            pyCheck.append("                dn = p[1]\n");
            pyCheck.append("                i1 = dn.rfind('[')\n");
            pyCheck.append("                i2 = dn.rfind(']')\n");
            pyCheck.append("                if i1 >= 0 and i2 > i1:\n");
            pyCheck.append("                    refs.append(dn[i1+1:i2].strip())\n");
            pyCheck.append("            cr = so.get('client_order_ref')\n");
            pyCheck.append("            if cr: refs.append(str(cr).strip())\n");
            pyCheck.append("            og = so.get('origin')\n");
            pyCheck.append("            if og: refs.append(str(og).strip())\n");
            pyCheck.append("        print(json.dumps({'refs': list(set(refs))}))\n");
            pyCheck.append("except Exception as e:\n");
            pyCheck.append("    print(json.dumps({'refs': [], 'error': str(e)}))\n");

            ProcessBuilder pb = new ProcessBuilder("python", "-c", pyCheck.toString());
            pb.redirectErrorStream(true);
            Process proc = pb.start();
            BufferedReader r = new BufferedReader(new InputStreamReader(proc.getInputStream()));
            StringBuilder outSb = new StringBuilder();
            String l;
            while ((l = r.readLine()) != null) outSb.append(l);
            proc.waitFor();
            JSONObject resObj = new JSONObject(outSb.toString());
            pList = resObj.optJSONArray("refs");
            if (pList == null) pList = new JSONArray();
        } catch (Exception ignore) {}
        out.print("{\"success\":true,\"confirmedRefs\":" + pList.toString() + "}");
        return;
    }

    // =========================================================================
    // 2. ACTION: CONFIRM QUOTATION IN ODOO & UNLOCK SAMPLE COLLECTION
    // =========================================================================
    if ("confirmQuotation".equals(action) || "confirm".equals(action)) {
        if (orderId == null || orderId.trim().isEmpty()) {
            out.print("{\"success\":false,\"error\":\"orderId is required\"}");
            return;
        }
        orderId = orderId.trim();
        if (patientId == null) patientId = "";
        patientId = patientId.trim();

        Session hSessionConf = null;
        Transaction txConf = null;
        String sampleUuid = "";
        try {
            hSessionConf = HibernateUtil.getSession();
            txConf = hSessionConf.beginTransaction();
            java.math.BigDecimal sid = new java.math.BigDecimal(orderId);
            java.math.BigDecimal csid = sid;
            try {
                List sCheck = hSessionConf.createSQLQuery("SELECT id FROM sample WHERE id = :sid").setParameter("sid", sid).list();
                if (sCheck == null || sCheck.isEmpty()) {
                    List shRows = hSessionConf.createSQLQuery("SELECT samp_id FROM sample_human WHERE id = :sid").setParameter("sid", sid).list();
                    if (shRows != null && !shRows.isEmpty() && shRows.get(0) != null) {
                        csid = new java.math.BigDecimal(shRows.get(0).toString().trim());
                    }
                }
            } catch (Exception ignore) {}

            try {
                List uList = hSessionConf.createSQLQuery("SELECT uuid FROM sample WHERE id = :csid LIMIT 1")
                    .setParameter("csid", csid).list();
                if (uList != null && !uList.isEmpty() && uList.get(0) != null) {
                    sampleUuid = uList.get(0).toString().trim();
                }
            } catch (Exception ignore) {}

            if (patientId.isEmpty()) {
                try {
                    List pRows = hSessionConf.createSQLQuery(
                        "SELECT pi.identity_data FROM sample_human sh " +
                        "JOIN patient_identity pi ON sh.patient_id = pi.patient_id " +
                        "WHERE (sh.samp_id = :csid OR sh.id = :csid) AND pi.identity_data IS NOT NULL AND TRIM(pi.identity_data) != '' " +
                        "ORDER BY LENGTH(pi.identity_data) ASC LIMIT 1"
                    ).setParameter("csid", csid).list();
                    if (pRows != null && !pRows.isEmpty() && pRows.get(0) != null) {
                        patientId = pRows.get(0).toString().trim();
                    }
                } catch (Exception ignore) {}
            }

            // Immediately mark stock_out_selection status = 'confirmed'
            hSessionConf.createSQLQuery("UPDATE stock_out_selection SET status = 'confirmed', sent_to_billing = TRUE, updated_at = CURRENT_TIMESTAMP WHERE sample_id = :csid OR sample_id = :sid")
                .setParameter("csid", csid).setParameter("sid", sid).executeUpdate();
            txConf.commit();
        } catch (Exception e) {
            if (txConf != null) try { txConf.rollback(); } catch (Exception ignore) {}
        } finally {
            try { HibernateUtil.closeSession(); } catch (Exception ignore) {}
        }

        // Asynchronously confirm the quotation in Odoo
        final String fPatRef = patientId;
        final String fSmUuid = sampleUuid;
        new Thread(new Runnable() {
            public void run() {
                try {
                    StringBuilder pyConf = new StringBuilder();
                    pyConf.append("import socket, xmlrpclib\n");
                    pyConf.append("socket.setdefaulttimeout(4.0)\n");
                    pyConf.append("try:\n");
                    pyConf.append("    common = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/common')\n");
                    pyConf.append("    uid = common.authenticate('odoo', 'emrsync', 'Admin123', {})\n");
                    pyConf.append("    pwd = 'Admin123'\n");
                    pyConf.append("    if not uid:\n");
                    pyConf.append("        uid = common.authenticate('odoo', 'admin', 'admin', {})\n");
                    pyConf.append("        pwd = 'admin'\n");
                    pyConf.append("    if uid:\n");
                    pyConf.append("        models = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/object')\n");
                    pyConf.append("        try:\n");
                    pyConf.append("            models.execute_kw('odoo', uid, pwd, 'api.event.worker', 'process_event', [{\n");
                    pyConf.append("                'category': 'confirm.sale.order',\n");
                    pyConf.append("                'patientId': '").append(fPatRef.replace("'", "\\'")).append("',\n");
                    pyConf.append("                'orderUuid': '").append(fSmUuid.replace("'", "\\'")).append("'\n");
                    pyConf.append("            }])\n");
                    pyConf.append("        except Exception:\n");
                    pyConf.append("            pass\n");
                    pyConf.append("        p_ref = '").append(fPatRef.replace("'", "\\'")).append("'\n");
                    pyConf.append("        so_ids = []\n");
                    pyConf.append("        if p_ref:\n");
                    pyConf.append("            partners = models.execute_kw('odoo', uid, pwd, 'res.partner', 'search', [[['ref', '=', p_ref]]])\n");
                    pyConf.append("            if partners:\n");
                    pyConf.append("                so_ids = models.execute_kw('odoo', uid, pwd, 'sale.order', 'search', [[['partner_id', 'in', partners], ['state', 'in', ['draft', 'sent']]]])\n");
                    pyConf.append("        if not so_ids and '").append(fSmUuid.replace("'", "\\'")).append("':\n");
                    pyConf.append("            so_ids = models.execute_kw('odoo', uid, pwd, 'sale.order', 'search', [[['origin', 'ilike', '").append(fSmUuid.replace("'", "\\'")).append("'], ['state', 'in', ['draft', 'sent']]]])\n");
                    pyConf.append("        for sid in so_ids:\n");
                    pyConf.append("            try:\n");
                    pyConf.append("                models.execute_kw('odoo', uid, pwd, 'sale.order', 'action_confirm', [[sid]])\n");
                    pyConf.append("            except Exception:\n");
                    pyConf.append("                models.execute_kw('odoo', uid, pwd, 'sale.order', 'write', [[sid], {'state': 'sale'}])\n");
                    pyConf.append("except Exception:\n");
                    pyConf.append("    pass\n");

                    ProcessBuilder pb = new ProcessBuilder("python", "-c", pyConf.toString());
                    Process proc = pb.start();
                    proc.waitFor();
                } catch (Exception ignore) {}
            }
        }).start();

        out.print("{\"success\":true,\"confirmed\":true,\"orderId\":\"" + orderId + "\",\"patientId\":\"" + patientId + "\"}");
        return;
    }

    // =========================================================================
    // 3. DEFAULT ACTION: SEND AVAILABLE TESTS TO ODOO & VOID STOCKOUT IN OPENMRS
    // =========================================================================
    if (orderId == null || orderId.trim().isEmpty()) {
        out.print("{\"success\":false,\"error\":\"orderId is required\"}");
        return;
    }
    orderId = orderId.trim();
    if (patientId == null) patientId = "";
    patientId = patientId.trim();
    boolean confirmNow = "true".equalsIgnoreCase(request.getParameter("confirmNow"));

                                    try {
                                    hSession = HibernateUtil.getSession();
                                    tx = hSession.beginTransaction();

                                    java.math.BigDecimal sid = new java.math.BigDecimal(orderId);
                                    java.math.BigDecimal csid = sid;
                                    try {
                                    List sCheck = hSession.createSQLQuery("SELECT id FROM sample WHERE id =
                                    :sid").setParameter("sid", sid).list();
                                    if (sCheck == null || sCheck.isEmpty()) {
                                    List shRows = hSession.createSQLQuery("SELECT samp_id FROM sample_human WHERE id =
                                    :sid").setParameter("sid", sid).list();
                                    if (shRows != null && !shRows.isEmpty() && shRows.get(0) != null) {
                                    csid = new java.math.BigDecimal(shRows.get(0).toString().trim());
                                    }
                                    }
                                    } catch (Exception ignore) {}

                                    // Mark sent_to_billing in stock_out_selection for this sample
                                    hSession.createSQLQuery("UPDATE stock_out_selection SET sent_to_billing = TRUE,
                                    updated_at = CURRENT_TIMESTAMP WHERE sample_id = :csid OR sample_id = :sid")
                                    .setParameter("csid", csid).setParameter("sid", sid).executeUpdate();

        // Mark sent_to_billing (and status = 'confirmed' if confirmNow)
        String newStatus = confirmNow ? "confirmed" : "available";
        hSession.createSQLQuery("UPDATE stock_out_selection SET sent_to_billing = TRUE, status = CASE WHEN status != 'stockout' THEN '" + newStatus + "' ELSE status END, updated_at = CURRENT_TIMESTAMP WHERE sample_id = :csid OR sample_id = :sid")
            .setParameter("csid", csid).setParameter("sid", sid).executeUpdate();

        // Find available test names for this sample
        org.hibernate.Query qAvail = hSession.createSQLQuery("SELECT DISTINCT CAST(test_name AS varchar), CAST(COALESCE(concept_uuid, '') AS varchar) FROM stock_out_selection WHERE (sample_id = :csid OR sample_id = :sid) AND status IN ('available', 'confirmed')")
            .setParameter("csid", csid).setParameter("sid", sid);
        List availList = qAvail.list();
        if (availList != null) {
            for (Object obj : availList) {
                if (obj instanceof Object[]) {
                    Object[] r = (Object[]) obj;
                    if (r[0] != null) availableNames.add(r[0].toString().trim());
                    if (r[1] != null && !r[1].toString().trim().isEmpty()) availableUuids.add(r[1].toString().trim());
                }
            }
        }

                                    // Find sample UUID for Odoo external_id mapping
                                    String sampleUuid = "";
                                    try {
                                    List uList = hSession.createSQLQuery("SELECT uuid FROM sample WHERE id = :csid LIMIT
                                    1")
                                    .setParameter("csid", csid).list();
                                    if (uList != null && !uList.isEmpty() && uList.get(0) != null) {
                                    sampleUuid = uList.get(0).toString().trim();
                                    }
                                    } catch (Exception ignore) {}

                                    // Fetch patientRef if empty
                                    if (patientId.isEmpty()) {
                                    try {
                                    List pRows = hSession.createSQLQuery(
                                    "SELECT pi.identity_data FROM sample_human sh " +
                                    "JOIN patient_identity pi ON sh.patient_id = pi.patient_id " +
                                    "WHERE (sh.samp_id = :csid OR sh.id = :csid) AND pi.identity_data IS NOT NULL AND
                                    TRIM(pi.identity_data) != '' " +
                                    "ORDER BY LENGTH(pi.identity_data) ASC LIMIT 1"
                                    ).setParameter("csid", csid).list();
                                    if (pRows != null && !pRows.isEmpty() && pRows.get(0) != null) {
                                    patientId = pRows.get(0).toString().trim();
                                    }
                                    } catch (Exception ignore) {}
                                    }

                                    tx.commit();

                                    // 1. Trigger Odoo add.available.lab.tests
                                    if (!availableNames.isEmpty() && !patientId.isEmpty()) {
                                    try {
                                    StringBuilder pyCmd = new StringBuilder();
                                    pyCmd.append("import xmlrpclib\n");
                                    pyCmd.append("common =
                                    xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/common')\n");
                                    pyCmd.append("uid = common.authenticate('odoo', 'emrsync', 'Admin123', {})\n");
                                    pyCmd.append("pwd = 'Admin123'\n");
                                    pyCmd.append("if not uid:\n");
                                    pyCmd.append(" uid = common.authenticate('odoo', 'admin', 'admin', {})\n");
                                    pyCmd.append(" pwd = 'admin'\n");
                                    pyCmd.append("if uid:\n");
                                    pyCmd.append(" models =
                                    xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/object')\n");
                                    pyCmd.append(" models.execute_kw('odoo', uid, pwd, 'api.event.worker',
                                    'process_event', [{\n");
                                    pyCmd.append(" 'category': 'add.available.lab.tests',\n");
                                    pyCmd.append(" 'patientId': '").append(patientId).append("',\n");
                                    pyCmd.append(" 'orderUuid': '").append(sampleUuid).append("',\n");
                                    pyCmd.append(" 'availableTestNames': [");
                                    for (int k = 0; k < availableNames.size(); k++) { if (k> 0) pyCmd.append(",");
                                        pyCmd.append("'").append(availableNames.get(k).replace("'", "\\'")).append("'");
                                        }
                                        pyCmd.append("],\n");
                                        pyCmd.append(" 'availableTestUuids': [");
                                        for (int k = 0; k < availableUuids.size(); k++) { if (k> 0) pyCmd.append(",");
                                            pyCmd.append("'").append(availableUuids.get(k).replace("'",
                                            "\\'")).append("'");
                                            }
                                            pyCmd.append("]\n");
                                            pyCmd.append(" }])\n");

        final List<String> fAvailNames = new ArrayList<String>(availableNames);
        final List<String> fAvailUuids = new ArrayList<String>(availableUuids);
        final List<String> fSoNames = new ArrayList<String>(stockOutNames);
        final String fPatId = patientId;
        final String fSampleUuid = sampleUuid;
        final boolean fConfirmNow = confirmNow;

        new Thread(new Runnable() {
            public void run() {
                // 1. Trigger Odoo add.available.lab.tests
                if (!fAvailNames.isEmpty() && !fPatId.isEmpty()) {
                    try {
                        StringBuilder pyCmd = new StringBuilder();
                        pyCmd.append("import socket, xmlrpclib\n");
                        pyCmd.append("socket.setdefaulttimeout(4.0)\n");
                        pyCmd.append("try:\n");
                        pyCmd.append("    common = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/common')\n");
                        pyCmd.append("    uid = common.authenticate('odoo', 'emrsync', 'Admin123', {})\n");
                        pyCmd.append("    pwd = 'Admin123'\n");
                        pyCmd.append("    if not uid:\n");
                        pyCmd.append("        uid = common.authenticate('odoo', 'admin', 'admin', {})\n");
                        pyCmd.append("        pwd = 'admin'\n");
                        pyCmd.append("    if uid:\n");
                        pyCmd.append("        models = xmlrpclib.ServerProxy('http://odoo:8069/xmlrpc/2/object')\n");
                        pyCmd.append("        models.execute_kw('odoo', uid, pwd, 'api.event.worker', 'process_event', [{\n");
                        pyCmd.append("            'category': 'add.available.lab.tests',\n");
                        pyCmd.append("            'patientId': '").append(fPatId.replace("'", "\\'")).append("',\n");
                        pyCmd.append("            'orderUuid': '").append(fSampleUuid.replace("'", "\\'")).append("',\n");
                        pyCmd.append("            'availableTestNames': [");
                        for (int k = 0; k < fAvailNames.size(); k++) {
                            if (k > 0) pyCmd.append(",");
                            pyCmd.append("'").append(fAvailNames.get(k).replace("'", "\\'")).append("'");
                        }
                        pyCmd.append("],\n");
                        pyCmd.append("            'availableTestUuids': [");
                        for (int k = 0; k < fAvailUuids.size(); k++) {
                            if (k > 0) pyCmd.append(",");
                            pyCmd.append("'").append(fAvailUuids.get(k).replace("'", "\\'")).append("'");
                        }
                        pyCmd.append("]\n");
                        pyCmd.append("        }])\n");
                        if (fConfirmNow) {
                            pyCmd.append("        try:\n");
                            pyCmd.append("            models.execute_kw('odoo', uid, pwd, 'api.event.worker', 'process_event', [{\n");
                            pyCmd.append("                'category': 'confirm.sale.order',\n");
                            pyCmd.append("                'patientId': '").append(fPatId.replace("'", "\\'")).append("',\n");
                            pyCmd.append("                'orderUuid': '").append(fSampleUuid.replace("'", "\\'")).append("'\n");
                            pyCmd.append("            }])\n");
                            pyCmd.append("        except Exception:\n");
                            pyCmd.append("            pass\n");
                        }
                        pyCmd.append("except Exception:\n");
                        pyCmd.append("    pass\n");

                        ProcessBuilder pb = new ProcessBuilder("python", "-c", pyCmd.toString());
                        Process proc = pb.start();
                        proc.waitFor();
                    } catch (Exception ignore) {}
                }

                // 2. Void stock-out tests in OpenMRS via REST API
                if (!fSoNames.isEmpty() && !fPatId.isEmpty()) {
                    try {
                        StringBuilder pyVoid = new StringBuilder();
                        pyVoid.append("import socket, urllib2, base64, json\n");
                        pyVoid.append("socket.setdefaulttimeout(4.0)\n");
                        pyVoid.append("try:\n");
                        pyVoid.append("    p_req = urllib2.Request('http://openmrs:8080/openmrs/ws/rest/v1/patient?q=").append(fPatId).append("&v=default')\n");
                        pyVoid.append("    p_req.add_header('Authorization', 'Basic ' + base64.b64encode('admin:Admin123'))\n");
                        pyVoid.append("    p_res = urllib2.urlopen(p_req)\n");
                        pyVoid.append("    p_data = json.loads(p_res.read())\n");
                        pyVoid.append("    if p_data.get('results'):\n");
                        pyVoid.append("        p_uuid = p_data['results'][0]['uuid']\n");
                        pyVoid.append("        o_req = urllib2.Request('http://openmrs:8080/openmrs/ws/rest/v1/order?patient=' + p_uuid + '&v=full')\n");
                        pyVoid.append("        o_req.add_header('Authorization', 'Basic ' + base64.b64encode('admin:Admin123'))\n");
                        pyVoid.append("        o_res = urllib2.urlopen(o_req)\n");
                        pyVoid.append("        orders_data = json.loads(o_res.read())\n");
                        pyVoid.append("        opener = urllib2.build_opener(urllib2.HTTPHandler)\n");
                        pyVoid.append("        so_list = [");
                        for (int k = 0; k < fSoNames.size(); k++) {
                            if (k > 0) pyVoid.append(",");
                            pyVoid.append("'").append(fSoNames.get(k).replace("'", "\\'").toLowerCase()).append("'");
                        }
                        pyVoid.append("]\n");
                        pyVoid.append("        for ord_item in orders_data.get('results', []):\n");
                        pyVoid.append("            disp = (ord_item.get('concept', {}).get('display') or '').strip().lower()\n");
                        pyVoid.append("            ouuid = ord_item.get('uuid')\n");
                        pyVoid.append("            for s_name in so_list:\n");
                        pyVoid.append("                if s_name in disp or disp in s_name or (s_name == 'rbs' and 'random blood sugar' in disp):\n");
                        pyVoid.append("                    v_req = urllib2.Request('http://openmrs:8080/openmrs/ws/rest/v1/order/' + ouuid + '?reason=Reagent+Out+of+Stock')\n");
                        pyVoid.append("                    v_req.get_method = lambda: 'DELETE'\n");
                        pyVoid.append("                    v_req.add_header('Authorization', 'Basic ' + base64.b64encode('admin:Admin123'))\n");
                        pyVoid.append("                    try:\n");
                        pyVoid.append("                        opener.open(v_req)\n");
                        pyVoid.append("                    except Exception:\n");
                        pyVoid.append("                        pass\n");
                        pyVoid.append("                    break\n");
                        pyVoid.append("except Exception:\n");
                        pyVoid.append("    pass\n");

                        ProcessBuilder pbVoid = new ProcessBuilder("python", "-c", pyVoid.toString());
                        Process procVoid = pbVoid.start();
                        procVoid.waitFor();
                    } catch (Exception ignore) {}
                }
            }
        }).start();

        out.print("{\"success\":true,\"orderId\":\"" + orderId + "\",\"patientId\":\"" + patientId + "\",\"availableCount\":" + availableNames.size() + ",\"stockOutCount\":" + stockOutNames.size() + ",\"confirmed\":" + confirmNow + "}");
    } catch (Exception e) {
        if (tx != null) try { tx.rollback(); } catch (Exception ex) {}
        out.print("{\"success\":false,\"error\":\"" + (e.getMessage() != null ? e.getMessage().replace("\"", "\\\"") : "error") + "\"}");
    } finally {
        try {
            HibernateUtil.closeSession();
        } catch (Exception ignore) {}
    }
%>