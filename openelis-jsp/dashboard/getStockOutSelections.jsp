<%@ page language="java" contentType="application/json; charset=utf-8" import="java.util.*,us.mn.state.health.lims.hibernate.HibernateUtil,org.hibernate.*,org.json.*,java.io.*"%><%
    response.setHeader("Cache-Control", "no-cache");
    String debug = request.getParameter("debug");
    if ("samples".equals(debug)) {
        Session hSession = null;
        try {
            hSession = HibernateUtil.getSession();
            List rows = hSession.createSQLQuery(
                "SELECT s.id, s.accession_number, s.entered_date, sh.id AS sh_id, sh.samp_id, pi.identity_data, p.first_name, p.last_name " +
                "FROM sample s " +
                "JOIN sample_human sh ON s.id = sh.samp_id " +
                "JOIN patient p ON sh.patient_id = p.id " +
                "JOIN patient_identity pi ON p.id = pi.patient_id " +
                "WHERE s.accession_number IS NULL " +
                "ORDER BY s.id DESC LIMIT 10"
            ).list();
            JSONArray arr = new JSONArray();
            if (rows != null) {
                for (Object o : rows) {
                    Object[] r = (Object[]) o;
                    JSONObject obj = new JSONObject();
                    obj.put("sample_id", r[0]);
                    obj.put("accession", r[1]);
                    obj.put("entered_date", r[2] != null ? r[2].toString() : "");
                    obj.put("sh_id", r[3]);
                    obj.put("sh_samp_id", r[4]);
                    obj.put("patient_id", r[5]);
                    obj.put("patient_name", (r[6] != null ? r[6] : "") + " " + (r[7] != null ? r[7] : ""));
                    arr.put(obj);
                }
            }
            out.print(arr.toString());
        } catch (Exception e) {
            out.print("{\"error\":\"" + e.getMessage() + "\"}");
        } finally {
            try { HibernateUtil.closeSession(); } catch (Exception ignore) {}
        }
        return;
    }
    String resetId = request.getParameter("resetSampleId");
    if (resetId != null && !resetId.trim().isEmpty()) {
        Session hSession = null;
        Transaction tx = null;
        try {
            hSession = HibernateUtil.getSession();
            tx = hSession.beginTransaction();
            java.math.BigDecimal rid = new java.math.BigDecimal(resetId.trim());
            hSession.createSQLQuery("DELETE FROM stock_out_selection WHERE sample_id = :rid OR sample_id IN (SELECT samp_id FROM sample_human WHERE id = :rid) OR sample_id IN (SELECT id FROM sample_human WHERE samp_id = :rid)").setParameter("rid", rid).executeUpdate();
            tx.commit();
            out.print("{\"success\":true,\"resetSampleId\":\"" + resetId + "\"}");
        } catch (Exception e) {
            if (tx != null) try { tx.rollback(); } catch (Exception ex) {}
            out.print("{\"success\":false,\"error\":\"" + e.getMessage() + "\"}");
        } finally {
            try { HibernateUtil.closeSession(); } catch (Exception ignore) {}
        }
        return;
    }

    String sampleId = request.getParameter("sampleId");
    if (sampleId == null || sampleId.trim().isEmpty()) {
        out.print("[]");
        return;
    }
    Session hSession = null;
    try {
        hSession = HibernateUtil.getSession();
        java.math.BigDecimal sid = new java.math.BigDecimal(sampleId.trim());
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

        // 1. Query previously saved selections for this canonical sample or sid
        org.hibernate.Query q = hSession.createSQLQuery(
            "SELECT DISTINCT ON (test_name) CAST(test_id AS varchar), CAST(test_name AS varchar), CAST(status AS varchar), CAST(COALESCE(concept_uuid, '') AS varchar) FROM stock_out_selection " +
            "WHERE sample_id = :csid OR sample_id = :sid " +
            "ORDER BY test_name, id DESC"
        ).setParameter("csid", csid).setParameter("sid", sid);
        List rows = q.list();

        // 2. If not yet evaluated, retrieve ordered tests directly from sample_item + analysis + test
        if (rows == null || rows.isEmpty()) {
            rows = hSession.createSQLQuery(
                "SELECT CAST(t.id AS varchar) AS test_id, CAST(t.name AS varchar) AS test_name, CAST('available' AS varchar) AS status, CAST(COALESCE(er.external_id, '') AS varchar) AS concept_uuid " +
                "FROM sample_item si " +
                "JOIN analysis a ON si.id = a.sampitem_id " +
                "JOIN test t ON a.test_id = t.id " +
                "LEFT JOIN external_reference er ON (t.id = er.item_id AND er.type = 'Test') " +
                "WHERE si.samp_id = :csid " +
                "ORDER BY t.name ASC"
            ).setParameter("csid", csid).list();
        }

        JSONArray arr = new JSONArray();
        if (rows != null) {
            for (Object row : rows) {
                Object[] cols = (Object[]) row;
                JSONObject obj = new JSONObject();
                obj.put("testId", cols[0] != null ? cols[0].toString() : "");
                obj.put("testName", cols[1] != null ? cols[1].toString() : "");
                String st = cols[2] != null ? cols[2].toString().trim() : "available";
                if (!"stockout".equalsIgnoreCase(st)) {
                    st = "available";
                }
                obj.put("status", st);
                obj.put("conceptUuid", cols.length > 3 && cols[3] != null ? cols[3].toString() : "");
                arr.put(obj);
            }
        }
        out.print(arr.toString());
    } catch (Exception e) {
        out.print("[]");
    } finally {
        try {
            HibernateUtil.closeSession();
        } catch (Exception ignore) {}
    }
%>