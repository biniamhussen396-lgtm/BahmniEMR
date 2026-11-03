package us.mn.state.health.lims.dashboard.daoimpl;

import java.io.PrintStream;
import java.net.URL;
import java.util.*;
import org.apache.xmlrpc.client.XmlRpcClient;
import org.apache.xmlrpc.client.XmlRpcClientConfigImpl;
import us.mn.state.health.lims.common.util.SystemConfiguration;
import us.mn.state.health.lims.dashboard.valueholder.Order;

public class OrderPayment {

    public static List<Order> setPatientPaymentStatus(List<Order> orders) {
        if (orders == null || orders.isEmpty()) {
            return orders;
        }

        if (!SystemConfiguration.getInstance().getIsPaymentRestrictive()) {
            for (Order order : orders) {
                order.setHasPaid(true);
            }
            return orders;
        }

        // Strict default: all orders are locked (hasPaid = false) until full invoice payment is verified
        for (Order order : orders) {
            order.setHasPaid(false);
        }

        try {
            List<String> orderUuids = new ArrayList<String>();
            for (Order order : orders) {
                if (order.getUuid() != null && !order.getUuid().trim().isEmpty()) {
                    orderUuids.add(order.getUuid().trim());
                }
            }

            if (orderUuids.isEmpty()) {
                return orders;
            }

            String odooURL = SystemConfiguration.getInstance().getOdooURL();
            String odooDB = SystemConfiguration.getInstance().getOdooDB();
            String odooUsername = SystemConfiguration.getInstance().getOdooUsername();
            String odooPassword = SystemConfiguration.getInstance().getOdooPassword();

            XmlRpcClient client = new XmlRpcClient();
            XmlRpcClientConfigImpl configCommon = new XmlRpcClientConfigImpl();
            configCommon.setServerURL(new URL(String.format("%s/xmlrpc/2/common", odooURL)));
            configCommon.setConnectionTimeout(5000);
            configCommon.setReplyTimeout(10000);

            Object authRes = client.execute(configCommon, "authenticate", Arrays.asList(new Object[] {
                odooDB, odooUsername, odooPassword, Collections.emptyMap()
            }));

            if (!(authRes instanceof Integer)) {
                return orders;
            }
            int uid = ((Integer) authRes).intValue();

            XmlRpcClient clientObj = new XmlRpcClient();
            XmlRpcClientConfigImpl configObj = new XmlRpcClientConfigImpl();
            configObj.setServerURL(new URL(String.format("%s/xmlrpc/2/object", odooURL)));
            configObj.setConnectionTimeout(5000);
            configObj.setReplyTimeout(10000);

            // 1. Search sale.order.line by external_id in orderUuids
            List<Object> filter = new ArrayList<Object>();
            filter.add(Arrays.asList(new Object[] { "external_id", "in", orderUuids }));

            Map<String, Object> lineKwargs = new HashMap<String, Object>();
            lineKwargs.put("fields", Arrays.asList(new String[] { "id", "external_id", "state", "invoice_status", "order_id" }));

            Object linesRes = clientObj.execute(configObj, "execute_kw", Arrays.asList(new Object[] {
                odooDB, Integer.valueOf(uid), odooPassword, "sale.order.line", "search_read",
                Arrays.asList(new Object[] { filter }),
                lineKwargs
            }));

            if (!(linesRes instanceof Object[])) {
                return orders;
            }

            Object[] lineArr = (Object[]) linesRes;
            if (lineArr.length == 0) {
                return orders;
            }

            Set<String> fullyPaidExternalIds = new HashSet<String>();
            Set<Integer> soIdsToQuery = new HashSet<Integer>();
            Map<Integer, List<String>> soToLineExtIds = new HashMap<Integer, List<String>>();

            for (Object item : lineArr) {
                if (item instanceof Map) {
                    Map lMap = (Map) item;
                    String extId = (String) lMap.get("external_id");
                    String lineState = (String) lMap.get("state");
                    String invStatus = (String) lMap.get("invoice_status");
                    Object orderIdField = lMap.get("order_id");

                    // Gate check: If line is confirmed in sale order ('sale' or 'done'), approve immediately!
                    if (("sale".equals(lineState) || "done".equals(lineState)) && extId != null) {
                        fullyPaidExternalIds.add(extId);
                    }

                    if (extId != null && orderIdField != null) {
                        Integer soId = null;
                        if (orderIdField instanceof Object[]) {
                            Object[] arr = (Object[]) orderIdField;
                            if (arr.length > 0 && arr[0] instanceof Integer) soId = (Integer) arr[0];
                        } else if (orderIdField instanceof List) {
                            List lst = (List) orderIdField;
                            if (!lst.isEmpty() && lst.get(0) instanceof Integer) soId = (Integer) lst.get(0);
                        }
                        if (soId != null) {
                            soIdsToQuery.add(soId);
                            if (!soToLineExtIds.containsKey(soId)) {
                                soToLineExtIds.put(soId, new ArrayList<String>());
                            }
                            soToLineExtIds.get(soId).add(extId);
                        }
                    }
                }
            }

            if (!soIdsToQuery.isEmpty()) {
                // 2. Read sale.order to retrieve related state and invoice_ids
                Map<String, Object> soKwargs = new HashMap<String, Object>();
                soKwargs.put("fields", Arrays.asList(new String[] { "id", "state", "invoice_ids" }));

                Object soRes = clientObj.execute(configObj, "execute_kw", Arrays.asList(new Object[] {
                    odooDB, Integer.valueOf(uid), odooPassword, "sale.order", "read",
                    Arrays.asList(new Object[] { new ArrayList<Integer>(soIdsToQuery) }),
                    soKwargs
                }));

                if (soRes instanceof Object[]) {
                    Set<Integer> allInvoiceIds = new HashSet<Integer>();
                    Map<Integer, List<Integer>> soToInvoices = new HashMap<Integer, List<Integer>>();

                    for (Object obj : (Object[]) soRes) {
                        if (obj instanceof Map) {
                            Map sMap = (Map) obj;
                            Integer soId = (Integer) sMap.get("id");
                            String soState = (String) sMap.get("state");
                            // If sale order is confirmed ('sale' or 'done'), approve all its lines immediately!
                            if (("sale".equals(soState) || "done".equals(soState)) && soId != null) {
                                List<String> extList = soToLineExtIds.get(soId);
                                if (extList != null) fullyPaidExternalIds.addAll(extList);
                            }

                            Object invIdsObj = sMap.get("invoice_ids");
                            List<Integer> invList = new ArrayList<Integer>();
                            if (invIdsObj instanceof Object[]) {
                                for (Object o : (Object[]) invIdsObj) if (o instanceof Integer) { invList.add((Integer) o); allInvoiceIds.add((Integer) o); }
                            } else if (invIdsObj instanceof List) {
                                for (Object o : (List) invIdsObj) if (o instanceof Integer) { invList.add((Integer) o); allInvoiceIds.add((Integer) o); }
                            }
                            if (soId != null) {
                                soToInvoices.put(soId, invList);
                            }
                        }
                    }

                    if (!allInvoiceIds.isEmpty()) {
                        // 3. Read account.move for payment verification
                        Map<String, Object> invKwargs = new HashMap<String, Object>();
                        invKwargs.put("fields", Arrays.asList(new String[] { "id", "state", "payment_state", "amount_residual" }));

                        Object invRes = clientObj.execute(configObj, "execute_kw", Arrays.asList(new Object[] {
                            odooDB, Integer.valueOf(uid), odooPassword, "account.move", "read",
                            Arrays.asList(new Object[] { new ArrayList<Integer>(allInvoiceIds) }),
                            invKwargs
                        }));

                        if (invRes instanceof Object[]) {
                            Map<Integer, Boolean> invoiceIsPaid = new HashMap<Integer, Boolean>();
                            for (Object obj : (Object[]) invRes) {
                                if (obj instanceof Map) {
                                    Map iMap = (Map) obj;
                                    Integer invId = (Integer) iMap.get("id");
                                    String state = (String) iMap.get("state");
                                    String paymentState = (String) iMap.get("payment_state");
                                    Object residualObj = iMap.get("amount_residual");
                                    double residual = 999999.0;
                                    if (residualObj instanceof Number) {
                                        residual = ((Number) residualObj).doubleValue();
                                    }
                                    boolean isPaid = "posted".equals(state) &&
                                                     ("paid".equals(paymentState) || "in_payment".equals(paymentState)) &&
                                                     residual <= 0.0001;
                                    invoiceIsPaid.put(invId, Boolean.valueOf(isPaid));
                                }
                            }

                            for (Map.Entry<Integer, List<Integer>> entry : soToInvoices.entrySet()) {
                                Integer soId = entry.getKey();
                                List<Integer> invIds = entry.getValue();
                                if (invIds == null || invIds.isEmpty()) continue;
                                boolean soPaid = true;
                                for (Integer iId : invIds) {
                                    Boolean p = invoiceIsPaid.get(iId);
                                    if (p == null || !p.booleanValue()) { soPaid = false; break; }
                                }
                                if (soPaid) {
                                    List<String> extIds = soToLineExtIds.get(soId);
                                    if (extIds != null) fullyPaidExternalIds.addAll(extIds);
                                }
                            }
                        }
                    }
                }
            }

            // Apply status to orders
            for (Order order : orders) {
                if (order.getUuid() != null && fullyPaidExternalIds.contains(order.getUuid().trim())) {
                    order.setHasPaid(true);
                } else {
                    order.setHasPaid(false);
                }
            }

        } catch (Throwable t) {
            System.err.println("Strict OrderPayment verification error: " + t.getMessage());
            // Strict security: Keep orders locked (hasPaid = false) on any error
            for (Order order : orders) {
                order.setHasPaid(false);
            }
        }

        return orders;
    }

    public static Boolean getPatientPaymentStatus(String orderUuid) {
        if (!SystemConfiguration.getInstance().getIsPaymentRestrictive()) {
            return Boolean.valueOf(true);
        }
        if (orderUuid == null || orderUuid.trim().isEmpty()) {
            return Boolean.valueOf(false);
        }
        Order dummy = new Order();
        dummy.setUuid(orderUuid.trim());
        List<Order> list = new ArrayList<Order>();
        list.add(dummy);
        setPatientPaymentStatus(list);
        return Boolean.valueOf(dummy.getHasPaid());
    }
}
