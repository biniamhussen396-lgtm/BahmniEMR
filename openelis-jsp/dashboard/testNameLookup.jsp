<%@ page language="java" contentType="application/json; charset=utf-8" import="java.util.*,us.mn.state.health.lims.hibernate.HibernateUtil,org.hibernate.*,us.mn.state.health.lims.test.valueholder.Test"%><%
    response.setHeader("Cache-Control", "no-cache");
    String idsParam = request.getParameter("ids");
    if (idsParam == null || idsParam.trim().isEmpty()) {
        out.print("{}");
        return;
    }
    String[] idStrs = idsParam.split(",");
    List<Integer> ids = new ArrayList<Integer>();
    for (String s : idStrs) {
        s = s.trim();
        if (!s.isEmpty()) {
            try { ids.add(Integer.parseInt(s)); } catch (Exception e) {}
        }
    }
    if (ids.isEmpty()) {
        out.print("{}");
        return;
    }
    Session hSession = null;
    try {
        hSession = HibernateUtil.getSession();
        StringBuilder sb = new StringBuilder("SELECT t.id, t.testName FROM Test t WHERE t.id IN (");
        for (int i = 0; i < ids.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append(":id" + i);
        }
        sb.append(")");
        Query q = hSession.createQuery(sb.toString());
        for (int i = 0; i < ids.size(); i++) {
            q.setParameter("id" + i, ids.get(i));
        }
        List results = q.list();
        out.print("{");
        boolean first = true;
        for (Object row : results) {
            Object[] cols = (Object[]) row;
            if (!first) out.print(",");
            String id = cols[0] != null ? cols[0].toString() : null;
            String name = cols[1] != null ? cols[1].toString() : "Test " + id;
            name = name.replace("\\", "\\\\").replace("\"", "\\\"").replace("'", "\\'");
            out.print("\"" + id + "\":\"" + name + "\"");
            first = false;
        }
        out.print("}");
    } catch (Exception e) {
        out.print("{\"error\":\"" + (e.getMessage() != null ? e.getMessage().replace("\"", "\\\"") : "unknown") + "\"}");
    } finally {
        try {
            HibernateUtil.closeSession();
        } catch (Exception ignore) {}
    }
%>