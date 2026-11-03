<%@ page language="java" contentType="application/json; charset=utf-8" import="java.util.*,us.mn.state.health.lims.hibernate.HibernateUtil,org.hibernate.*,org.json.*,java.io.*,java.net.*"%><%@ page import="javax.net.ssl.*"%><%
    response.setHeader("Cache-Control", "no-cache");
    StringBuilder bodyBuilder = new StringBuilder();
    BufferedReader reader = request.getReader();
    String line;
    while ((line = reader.readLine()) != null) bodyBuilder.append(line);
    String body = bodyBuilder.toString();

    JSONObject json = new JSONObject(body);
    String accessionNumber = json.optString("accessionNumber", "");
    String noticeNumber = json.optString("noticeNumber", "");
    String patientName = json.optString("patientName", "");
    String orderId = json.optString("orderId", "");
    JSONArray stockOutTests = null;
    Object sotObj = json.opt("stockOutTests");
    if (sotObj instanceof JSONArray) {
        stockOutTests = (JSONArray) sotObj;
    } else if (sotObj instanceof String) {
        String sotStr = ((String) sotObj).trim();
        if (!sotStr.isEmpty()) {
            try {
                stockOutTests = new JSONArray(sotStr);
            } catch (Exception ignore) {}
        }
    }

    Session hSession = null;
    Transaction tx = null;
    try {
        hSession = HibernateUtil.getSession();
        tx = hSession.beginTransaction();

        String refNumber = accessionNumber.isEmpty() ? orderId : accessionNumber;

        hSession.createSQLQuery("INSERT INTO stock_out_notice (notice_number, notice_date, accession_number, patient_name, void_reason, is_printed, created_at, updated_at) VALUES (:nn, CURRENT_TIMESTAMP, :an, :pn, 'Reagent Stock Out', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            .setParameter("nn", noticeNumber)
            .setParameter("an", refNumber)
            .setParameter("pn", patientName)
            .executeUpdate();

        Number noticeIdNum = (Number) hSession.createSQLQuery("SELECT id FROM stock_out_notice WHERE notice_number = :nn")
            .setParameter("nn", noticeNumber).uniqueResult();
        int noticeId = noticeIdNum.intValue();

        List sampleIds;
        if (accessionNumber.isEmpty()) {
            sampleIds = hSession.createSQLQuery("SELECT id FROM sample WHERE id = :sid")
                .setParameter("sid", new java.math.BigDecimal(orderId)).list();
        } else {
            sampleIds = hSession.createSQLQuery("SELECT id FROM sample WHERE accession_number = :an")
                .setParameter("an", accessionNumber).list();
        }

        if (stockOutTests != null) {
            for (int i = 0; i < stockOutTests.length(); i++) {
                JSONObject tObj = stockOutTests.getJSONObject(i);
                String testName = tObj.optString("testName", "");
                String testIdStr = tObj.optString("testId", "");

                hSession.createSQLQuery("INSERT INTO stock_out_notice_item (notice_id, test_id, test_name, void_reason, void_time, created_at) VALUES (:nid, :tid, :tn, 'Reagent Stock Out', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
                    .setParameter("nid", noticeId)
                    .setParameter("tid", testIdStr.isEmpty() ? 0 : Integer.parseInt(testIdStr))
                    .setParameter("tn", testName)
                    .executeUpdate();

                if (!testIdStr.isEmpty() && !sampleIds.isEmpty()) {
                    String sampIdList = "";
                    for (Object sid : sampleIds) {
                        if (!sampIdList.isEmpty()) sampIdList += ",";
                        sampIdList += sid.toString();
                    }
                    hSession.createSQLQuery("UPDATE analysis SET status_id = 15, lastupdated = CURRENT_TIMESTAMP WHERE test_id = :tid AND sampitem_id IN (SELECT si.id FROM sample_item si WHERE si.samp_id IN (" + sampIdList + ")) AND status_id != 15")
                        .setParameter("tid", Integer.parseInt(testIdStr))
                        .executeUpdate();
                }
            }
        }

        tx.commit();

        // Call Odoo to cancel stock-out test order lines via JSON-RPC
        String odooResult = "skipped";
        if (stockOutTests != null && stockOutTests.length() > 0) {
            try {
                String[] testNames = new String[stockOutTests.length()];
                for (int i = 0; i < stockOutTests.length(); i++) {
                    testNames[i] = stockOutTests.getJSONObject(i).optString("testName", "");
                }
                odooResult = cancelOdooLines(refNumber, testNames);
            } catch (Exception odooErr) {
                odooResult = "error: " + odooErr.getMessage();
            }
        }

        out.print("{\"success\":true,\"noticeId\":" + noticeId + ",\"noticeNumber\":\"" + noticeNumber + "\",\"odoo\":\"" + odooResult + "\"}");
    } catch (Exception e) {
        if (tx != null) try { tx.rollback(); } catch (Exception ex) {}
        String msg = e.getMessage() != null ? e.getMessage().replace("\"", "\\\"").replace("\n", " ") : "unknown error";
        out.print("{\"success\":false,\"error\":\"" + msg + "\"}");
    } finally {
        try {
            HibernateUtil.closeSession();
        } catch (Exception ignore) {}
    }
%><%!
    private static final String ODOO_URL = "http://odoo:8069";
    private static final String ODOO_DB = "odoo";
    private static final String ODOO_USER = "admin";
    private static final String ODOO_PASS = "admin";
    private String lastSetCookie;

    private String cancelOdooLines(String accessionNumber, String[] stockOutTestNames) throws Exception {
        // Step 1: Authenticate and get session_id
        JSONObject authPayload = new JSONObject();
        authPayload.put("jsonrpc", "2.0");
        authPayload.put("method", "call");
        authPayload.put("id", 1);
        JSONObject authParams = new JSONObject();
        authParams.put("db", ODOO_DB);
        authParams.put("login", ODOO_USER);
        authParams.put("password", ODOO_PASS);
        authPayload.put("params", authParams);

        lastSetCookie = null;
        String authResp = httpPost(ODOO_URL + "/web/session/authenticate", authPayload.toString());
        JSONObject authJson = new JSONObject(authResp);
        JSONObject authResult = authJson.optJSONObject("result");
        if (authResult == null) return "auth_failed";
        String sessionId = authResult.optString("session_id", "");
        if (sessionId.isEmpty() && lastSetCookie != null) {
            for (String cookiePart : lastSetCookie.split(";")) {
                cookiePart = cookiePart.trim();
                if (cookiePart.startsWith("session_id=")) {
                    sessionId = cookiePart.substring("session_id=".length());
                    break;
                }
            }
        }
        if (sessionId.isEmpty()) return "auth_failed";

        String cookie = "session_id=" + sessionId;

        // Step 2: Find sale orders in draft with this accession number in origin
        JSONObject searchPayload = new JSONObject();
        searchPayload.put("jsonrpc", "2.0");
        searchPayload.put("method", "call");
        searchPayload.put("id", 2);
        JSONObject searchKwargs = new JSONObject();
        JSONArray domain = new JSONArray();
        domain.put(new JSONArray().put("origin").put("ilike").put(accessionNumber));
        domain.put(new JSONArray().put("state").put("=").put("draft"));
        searchKwargs.put("domain", domain);
        searchKwargs.put("fields", new JSONArray().put("name").put("order_line"));
        searchKwargs.put("limit", 5);
        searchPayload.put("params", new JSONObject()
            .put("model", "sale.order")
            .put("method", "search_read")
            .put("args", new JSONArray())
            .put("kwargs", searchKwargs));

        String searchResp = httpPostWithCookie(ODOO_URL + "/web/dataset/call_kw", searchPayload.toString(), cookie);
        JSONObject searchJson = new JSONObject(searchResp);
        JSONArray orders = searchJson.optJSONArray("result");
        if (orders == null || orders.length() == 0) return "no_order_found";

        int cancelledCount = 0;
        for (int o = 0; o < orders.length(); o++) {
            JSONObject order = orders.getJSONObject(o);
            JSONArray orderLineIds = order.optJSONArray("order_line");
            if (orderLineIds == null || orderLineIds.length() == 0) continue;

            // Step 3: Read each order line to get product name
            JSONObject readPayload = new JSONObject();
            readPayload.put("jsonrpc", "2.0");
            readPayload.put("method", "call");
            readPayload.put("id", 3);
            readPayload.put("params", new JSONObject()
                .put("model", "sale.order.line")
                .put("method", "read")
                .put("args", new JSONArray().put(orderLineIds))
                .put("kwargs", new JSONObject().put("fields", new JSONArray().put("name").put("product_id"))));

            String readResp = httpPostWithCookie(ODOO_URL + "/web/dataset/call_kw", readPayload.toString(), cookie);
            JSONObject readJson = new JSONObject(readResp);
            JSONArray lines = readJson.optJSONArray("result");
            if (lines == null) continue;

            // Step 4: Find lines matching stock-out test names and unlink them
            JSONArray linesToDelete = new JSONArray();
            for (int l = 0; l < lines.length(); l++) {
                JSONObject line = lines.getJSONObject(l);
                String productName = line.optString("name", "").toLowerCase();
                for (String testName : stockOutTestNames) {
                    if (testName.toLowerCase().equals(productName) || productName.contains(testName.toLowerCase())) {
                        linesToDelete.put(line.getInt("id"));
                        break;
                    }
                }
            }

            if (linesToDelete.length() > 0) {
                JSONObject unlinkPayload = new JSONObject();
                unlinkPayload.put("jsonrpc", "2.0");
                unlinkPayload.put("method", "call");
                unlinkPayload.put("id", 4);
                unlinkPayload.put("params", new JSONObject()
                    .put("model", "sale.order.line")
                    .put("method", "unlink")
                    .put("args", new JSONArray().put(linesToDelete))
                    .put("kwargs", new JSONObject()));

                String unlinkResp = httpPostWithCookie(ODOO_URL + "/web/dataset/call_kw", unlinkPayload.toString(), cookie);
                JSONObject unlinkJson = new JSONObject(unlinkResp);
                if (unlinkJson.optBoolean("result", false)) {
                    cancelledCount += linesToDelete.length();

                    // Check if order has no lines left → cancel it
                    int remainingLines = lines.length() - linesToDelete.length();
                    if (remainingLines == 0) {
                        int orderId = order.getInt("id");
                        JSONObject cancelPayload = new JSONObject();
                        cancelPayload.put("jsonrpc", "2.0");
                        cancelPayload.put("method", "call");
                        cancelPayload.put("id", 5);
                        cancelPayload.put("params", new JSONObject()
                            .put("model", "sale.order")
                            .put("method", "action_cancel")
                            .put("args", new JSONArray().put(new JSONArray().put(orderId)))
                            .put("kwargs", new JSONObject()));

                        httpPostWithCookie(ODOO_URL + "/web/dataset/call_kw", cancelPayload.toString(), cookie);
                    }
                }
            }
        }

        return "cancelled_" + cancelledCount + "_lines";
    }

    private String httpPost(String urlStr, String body) throws Exception {
        URL url = new URL(urlStr);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setDoOutput(true);
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(10000);
        OutputStream os = conn.getOutputStream();
        os.write(body.getBytes("UTF-8"));
        os.flush();
        os.close();
        int code = conn.getResponseCode();
        lastSetCookie = conn.getHeaderField("Set-Cookie");
        InputStream is = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
        BufferedReader br = new BufferedReader(new InputStreamReader(is));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line);
        br.close();
        conn.disconnect();
        return sb.toString();
    }

    private String httpPostWithCookie(String urlStr, String body, String cookie) throws Exception {
        URL url = new URL(urlStr);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("Cookie", cookie);
        conn.setDoOutput(true);
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(10000);
        OutputStream os = conn.getOutputStream();
        os.write(body.getBytes("UTF-8"));
        os.flush();
        os.close();
        int code = conn.getResponseCode();
        InputStream is = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
        BufferedReader br = new BufferedReader(new InputStreamReader(is));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line);
        br.close();
        conn.disconnect();
        return sb.toString();
    }
%>