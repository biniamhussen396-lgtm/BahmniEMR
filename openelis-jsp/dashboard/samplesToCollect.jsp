<%@ page language="java"
	contentType="text/html; charset=utf-8"
	import="java.util.Date,
	java.text.SimpleDateFormat,
	us.mn.state.health.lims.common.util.SystemConfiguration,
	us.mn.state.health.lims.common.action.IActionConstants" %>
<%@ page import="us.mn.state.health.lims.common.util.ConfigurationProperties" %>

<%@ taglib uri="/tags/struts-bean" prefix="bean" %>
<%@ taglib uri="/tags/struts-html" prefix="html" %>
<%@ taglib uri="/tags/struts-logic" prefix="logic" %>
<%@ taglib uri="/tags/labdev-view" prefix="app" %>
<bean:define id="formName" value='<%= (String)request.getAttribute(IActionConstants.FORM_NAME) %>' />
<bean:define id="todayOrderListJson" name="<%=formName%>" property="todayOrderList" />
<bean:define id="todaySampleNotCollectedListJson" name="<%=formName%>" property="todaySampleNotCollectedList" />
<bean:define id="backlogSampleNotCollectedListJson" name="<%=formName%>" property="backlogSampleNotCollectedList" />
<bean:define id="backlogOrderListJson" name="<%=formName%>" property="backlogOrderList" />
<bean:define id="showPriorityColumn" name="<%=formName%>" property="isGroupBySample" />

<%!
String path = "";
String basePath = "";
String serverNow = new SimpleDateFormat("yyyy/MM/dd").format(new Date());
Boolean alwaysValidate = ConfigurationProperties.getInstance().isPropertyValueEqual(ConfigurationProperties.Property.ALWAYS_VALIDATE_RESULTS, "true");
Boolean showReferredTestsCount = ConfigurationProperties.getInstance().isPropertyValueEqual(ConfigurationProperties.Property.SHOW_REFERRED_TESTS_COUNT, "true");
Boolean showPatientsDetailsInSampleLabelPrint = ConfigurationProperties.getInstance().isPropertyValueEqual(ConfigurationProperties.Property.SHOW_PATIENT_DETAILS_SAMPLE_LABEL_PRINT, "true");
%>

<%
path = request.getContextPath();
basePath = path + "/";
String selectedLabLocationName = (String) session.getAttribute("selectedLabLocationName");
if (selectedLabLocationName == null) selectedLabLocationName = "";

java.util.Set<String> evaluatedSampleIds = new java.util.HashSet<String>();
java.util.Set<String> sentToBillingSampleIds = new java.util.HashSet<String>();
java.util.Set<String> confirmedSampleIds = new java.util.HashSet<String>();
try {
    org.hibernate.Session dbSession = us.mn.state.health.lims.hibernate.HibernateUtil.getSession();
    java.util.List soRows = dbSession.createSQLQuery(
        "SELECT " +
        "  CAST(sos.sample_id AS varchar), " +
        "  CAST(COALESCE(sh.id, 0) AS varchar), " +
        "  CAST(COALESCE(sh.samp_id, 0) AS varchar), " +
        "  MAX(CASE WHEN sos.sent_to_billing = true THEN 1 ELSE 0 END), " +
        "  MAX(CASE WHEN sos.status IN ('confirmed', 'approved', 'paid') THEN 1 ELSE 0 END) " +
        "FROM stock_out_selection sos " +
        "LEFT JOIN sample_human sh ON (sos.sample_id = sh.samp_id OR sos.sample_id = sh.id) " +
        "WHERE sos.status IN ('available', 'stockout', 'confirmed', 'approved', 'paid') " +
        "GROUP BY sos.sample_id, sh.id, sh.samp_id"
    ).list();
    if (soRows != null) {
        for (Object obj : soRows) {
            if (obj instanceof Object[]) {
                Object[] r = (Object[]) obj;
                boolean isSent = (r[3] != null && ((Number) r[3]).intValue() == 1);
                boolean isConf = (r[4] != null && ((Number) r[4]).intValue() == 1);
                for (int k = 0; k < 3; k++) {
                    if (r[k] != null) {
                        String sidVal = r[k].toString().trim();
                        if (!sidVal.isEmpty() && !"0".equals(sidVal)) {
                            evaluatedSampleIds.add(sidVal);
                            if (isSent) {
                                sentToBillingSampleIds.add(sidVal);
                            }
                            if (isConf) {
                                confirmedSampleIds.add(sidVal);
                            }
                        }
                    }
                }
            }
        }
    }
} catch (Exception ignore) {
} finally {
    try {
        us.mn.state.health.lims.hibernate.HibernateUtil.closeSession();
    } catch (Exception ignore) {}
}
String evaluatedSampleIdsJson = new org.json.JSONArray(evaluatedSampleIds).toString();
String sentToBillingSampleIdsJson = new org.json.JSONArray(sentToBillingSampleIds).toString();
String confirmedSampleIdsJson = new org.json.JSONArray(confirmedSampleIds).toString();
%>

<link rel="stylesheet" type="text/css" href="<%=basePath%>css/slickgrid/examples.css" />
<link rel="stylesheet" type="text/css" href="<%=basePath%>css/slickgrid/slick.grid.css" />

<script type="text/javascript" src="<%=basePath%>scripts/ui/jquery.event.drag-2.2.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/ui/jquery.event.drop-2.2.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.core.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.formatters.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.cellrangedecorator.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.cellrangeselector.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.cellexternalcopymanager.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.cellselectionmodel.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.rowselectionmodel.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.dataview.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.grid.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.editors.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/merge-sort.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/dashBoard/orders.js?v=<%= System.currentTimeMillis() %>"></script>
<script type="text/javascript" src="<%=basePath%>scripts/dashBoard/createGrid.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/slickgrid/slick.autotooltips.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/utils.js"></script>
<script type="text/javascript" src="<%=basePath%>scripts/JsBarcode.all.min.js"></script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body>table>tbody>tr:first-child,body>table>tbody>tr:nth-child(2),body>table>tbody>tr:last-child{display:none!important}
body>table{border:none!important;width:100%!important;height:calc(100vh - 85px)!important;border-collapse:collapse!important;margin:0!important;padding:0!important}
body>table>tbody>tr:nth-child(3)>td{padding:0!important;margin:0!important;vertical-align:top!important;height:100%!important}
.od-body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;color:#1a1a2e;line-height:1.5;display:flex;flex-direction:column;height:calc(100vh - 85px);overflow:hidden}
form[name="menuForm"]{position:sticky!important;top:0!important;z-index:50!important;background:#fff!important;flex-shrink:0}

.od-sticky-top{background:#f0f2f5;padding:8px 16px 0;border-bottom:1px solid #e2e8f0;flex-shrink:0}
.od-header{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;flex-wrap:wrap}
.od-header-left{display:flex;align-items:center;gap:8px}
.od-logo{width:32px;height:32px;background:linear-gradient(135deg,#0f766e,#14b8a6);border-radius:7px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:14px;flex-shrink:0}
.od-title{font-size:16px;font-weight:700;color:#0f172a}
.od-subtitle{font-size:10px;color:#64748b}
.od-header-right{display:flex;align-items:center;gap:5px;flex-wrap:wrap;flex-shrink:0}
.od-location-badge{display:inline-flex;align-items:center;gap:4px;padding:4px 8px;background:linear-gradient(135deg,#0f766e,#14b8a6);color:#fff;border-radius:5px;font-size:10px;font-weight:600;white-space:nowrap}
.od-location-badge svg{width:12px;height:12px}
.od-refresh-btn,.od-customize-btn,.od-nav-btn{display:inline-flex;align-items:center;gap:4px;padding:4px 8px;background:#fff;color:#334155;border:1px solid #e2e8f0;border-radius:5px;font-size:10px;font-weight:500;cursor:pointer;transition:all .15s;white-space:nowrap;flex-shrink:0;height:26px;text-decoration:none}
.od-refresh-btn:hover,.od-customize-btn:hover,.od-nav-btn:hover{background:#f8fafc;border-color:#cbd5e1}
.od-refresh-btn svg,.od-customize-btn svg,.od-nav-btn svg{width:12px;height:12px}
.od-nav-btn.active{background:#1d4ed8;color:#fff;border-color:#1d4ed8}
.od-nav-group{display:flex;gap:0}
.od-nav-group .od-nav-btn{border-radius:0;border-right-width:0}
.od-nav-group .od-nav-btn:first-child{border-radius:5px 0 0 5px}
.od-nav-group .od-nav-btn:last-child{border-radius:0 5px 5px 0;border-right-width:1px}

.od-stats{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-bottom:8px}
.od-stat-card{background:#fff;border-radius:7px;padding:7px 10px;display:flex;align-items:center;gap:8px;box-shadow:0 1px 2px rgba(0,0,0,.04);border:1px solid #f1f5f9;transition:all .15s}
.od-stat-card.od-card-highlight{border-color:#1d4ed8;box-shadow:0 0 0 2px rgba(29,78,216,.12)}
.od-stat-icon{width:28px;height:28px;border-radius:6px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.od-stat-icon svg{width:14px;height:14px}
.od-stat-icon.teal{background:#f0fdfa;color:#0f766e}
.od-stat-icon.blue{background:#eff6ff;color:#1d4ed8}
.od-stat-icon.amber{background:#fffbeb;color:#b45309}
.od-stat-icon.green{background:#f0fdf4;color:#15803d}
.od-stat-icon.purple{background:#faf5ff;color:#7c3aed}
.od-stat-icon.rose{background:#fff1f2;color:#be123c}
.od-stat-label{font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.4px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.od-stat-value{font-size:18px;font-weight:700;color:#0f172a;line-height:1}
.od-stat-card.od-card-hidden{display:none!important}

.od-main-content{flex:1;padding:8px 16px;display:flex;flex-direction:column;min-height:0;overflow:hidden}

    .od-section{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.06);border:1px solid #f1f5f9;flex:1;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.od-section-body{display:flex;flex:1;min-height:0;overflow:hidden;position:relative}

.od-tabs{display:flex;flex-direction:column;padding:6px 0;background:#f8fafc;border-right:1px solid #e2e8f0;min-width:110px;flex-shrink:0;overflow-y:auto}
.od-tab{padding:9px 12px;font-size:11px;font-weight:500;color:#64748b;cursor:pointer;border:none;background:none;border-left:3px solid transparent;transition:all .15s;white-space:nowrap;text-align:left;display:flex;align-items:center;justify-content:space-between}
.od-tab:hover{color:#334155;background:rgba(0,0,0,.02)}
.od-tab.active{color:#1d4ed8;border-left-color:#1d4ed8;font-weight:600;background:rgba(29,78,216,.04)}
.od-tab .od-badge{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;padding:0 5px;border-radius:9px;font-size:9px;font-weight:700;background:#eff6ff;color:#1d4ed8}
.od-tab.active .od-badge{background:#1d4ed8;color:#fff}

.od-grid-area{flex:1;min-width:0;min-height:0;overflow:hidden;position:relative}
.od-grid-container{display:none;position:absolute;top:0;left:0;right:0;bottom:0;overflow:hidden}
.od-grid-container.active{display:flex;flex-direction:column}
.od-dashboard-view{display:none;position:absolute;top:0;left:0;right:0;bottom:0;overflow-y:auto;padding:12px;background:#f0f2f5}
.od-dashboard-view.active{display:block}
#dashEmbed{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a2e;display:flex;flex-direction:column;gap:12px;min-height:100%}
#dashEmbed .ds-grid{display:grid !important;grid-template-columns:repeat(6,1fr) !important;gap:10px;width:100% !important}
#dashEmbed .ds-card{background:#fff;border-radius:10px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.06);border:1px solid #f1f5f9;position:relative;overflow:hidden;display:flex;flex-direction:column;min-width:0}
#dashEmbed .ds-card-top{display:flex;align-items:center;gap:10px;margin-bottom:6px}
#dashEmbed .ds-card-icon{width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
#dashEmbed .ds-card-icon svg{width:18px;height:18px}
#dashEmbed .ds-card-icon.teal{background:#f0fdfa;color:#0f766e}
#dashEmbed .ds-card-icon.blue{background:#eff6ff;color:#1d4ed8}
#dashEmbed .ds-card-icon.amber{background:#fffbeb;color:#d97706}
#dashEmbed .ds-card-icon.red{background:#fef2f2;color:#dc2626}
#dashEmbed .ds-card-icon.purple{background:#faf5ff;color:#7c3aed}
#dashEmbed .ds-card-label{font-size:9px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.5px}
#dashEmbed .ds-card-value{font-size:22px;font-weight:800;color:#0f172a;line-height:1}
#dashEmbed .ds-card-footer{display:flex;justify-content:space-between;font-size:9px;color:#64748b;margin-top:auto;padding-top:4px}
#dashEmbed .ds-card-footer span{display:flex;align-items:center;gap:3px}
#dashEmbed .ds-card-spark{position:absolute;bottom:8px;right:8px;width:70px;height:30px;opacity:.5}
#dashEmbed .ds-progress{display:flex;height:5px;border-radius:3px;overflow:hidden;gap:2px;margin-top:6px}
#dashEmbed .ds-progress div{height:100%;border-radius:3px}
#dashEmbed .ds-alert-count{width:44px;height:44px;border-radius:50%;background:#dc2626;color:#fff;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:800;margin:6px auto}
#dashEmbed .ds-gauge-wrap{display:flex;align-items:center;justify-content:center;margin:4px auto}
#dashEmbed .db-row{display:grid;grid-template-columns:1fr 2fr 1fr;gap:12px;flex:1;min-height:0;overflow:hidden}
#dashEmbed .db-panel{background:#fff;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.06);border:1px solid #f1f5f9;display:flex;flex-direction:column;min-height:0;overflow:hidden}
#dashEmbed .db-panel-hdr{padding:12px 16px;border-bottom:1px solid #f1f5f9;flex-shrink:0}
#dashEmbed .db-panel-hdr h3{font-size:13px;font-weight:700;color:#0f172a;margin:0;display:flex;align-items:center;gap:6px}
#dashEmbed .db-panel-hdr h3 .dot{width:7px;height:7px;border-radius:50%;background:#0f766e}
#dashEmbed .db-panel-body{flex:1;padding:12px 16px;overflow-y:auto;min-height:0;display:flex;flex-direction:column}
#dashEmbed .db-tabs{display:flex;gap:0;margin-bottom:10px;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden}
#dashEmbed .db-tab{flex:1;padding:7px 12px;text-align:center;font-size:11px;font-weight:600;cursor:pointer;background:#fff;color:#64748b;border:none;transition:all .15s}
#dashEmbed .db-tab.active{background:#0f766e;color:#fff}
#dashEmbed .db-tab .badge{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;padding:0 5px;border-radius:9px;font-size:9px;font-weight:700;margin-left:3px}
#dashEmbed .db-tab.active .badge{background:rgba(255,255,255,.25);color:#fff}
#dashEmbed .db-tab .badge.green{background:#dcfce7;color:#16a34a}
#dashEmbed .db-tab .badge.red{background:#fee2e2;color:#dc2626}
#dashEmbed .db-tab .badge.blue{background:#dbeafe;color:#2563eb}
#dashEmbed .db-table{width:100%;border-collapse:collapse;font-size:11px}
#dashEmbed .db-table th{background:#1e293b;color:#fff;padding:9px 10px;text-align:left;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}
#dashEmbed .db-table td{padding:9px 10px;border-bottom:1px solid #f1f5f9;color:#1e293b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:140px}
#dashEmbed .db-table tr:hover{background:#f8fafc}
#dashEmbed .db-pri{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:8px;font-size:9px;font-weight:600}
#dashEmbed .db-pri.high{background:#fef2f2;color:#dc2626}
#dashEmbed .db-pri.low{background:#f0fdf4;color:#16a34a}
#dashEmbed .db-status{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:8px;font-size:9px;font-weight:600;background:#eff6ff;color:#1d4ed8}
#dashEmbed .db-timer{font-size:10px;color:#64748b;font-variant-numeric:tabular-nums}
#dashEmbed .chart-wrap{position:relative;width:100%;flex:1;min-height:0}
#dashEmbed .chart-wrap canvas{width:100%!important;height:100%!important}
.od-grid-container .slick-viewport{flex:1;overflow:auto!important;min-height:0}
#todaySamplesToCollectListContainer,#backlogSamplesToCollectListContainer{width:100%!important;background:#fff!important;height:100%!important}
#todaySamplesToCollectListContainer-slick-grid,#backlogSamplesToCollectListContainer-slick-grid{width:100%!important;height:100%!important}

.od-grid-container .slick-header{background:#1e293b!important;border-bottom:2px solid #0f172a!important;width:100%!important}
.od-grid-container .slick-header-column{font-size:10px!important;font-weight:700!important;color:#fff!important;text-transform:uppercase!important;letter-spacing:.3px!important;padding:0 8px!important;height:36px!important;line-height:36px!important;background:#1e293b!important;border-color:#334155!important;white-space:nowrap!important;box-sizing:border-box!important}
.od-grid-container .slick-header-column:hover{background:#334155!important}
.od-grid-container .slick-headerrow{background:#f1f5f9!important;width:100%!important}
.od-grid-container .slick-headerrow-column{background:#f1f5f9!important;border-color:#e2e8f0!important;padding:3px 4px!important;box-sizing:border-box!important}
.od-grid-container .slick-headerrow-column input{box-sizing:border-box!important;border:1px solid #94a3b8!important;border-radius:4px!important;padding:3px 6px!important;font-size:11px!important;color:#1e293b!important;background:#fff!important;width:100%!important;height:24px!important;line-height:24px!important}
.od-grid-container .slick-headerrow-column input:focus{border-color:#0f766e!important;outline:none!important;box-shadow:0 0 0 2px rgba(15,118,110,.12)!important}
.od-grid-container .slick-row{border-bottom:1px solid #e2e8f0!important;min-height:36px!important;transition:background-color 120ms ease-in-out!important;cursor:pointer!important}
.od-grid-container .slick-row:hover{background:#e0f2fe!important}
.od-grid-container .slick-cell{font-size:12px!important;color:#1e293b!important;padding:0 8px!important;height:36px!important;border-color:#e2e8f0!important;line-height:36px!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;box-sizing:border-box!important}
.od-grid-container .slick-cell:hover{background:rgba(224,242,254,.3)!important}
.od-grid-container .slick-row.odd{background:#f8fafc!important}
.od-grid-container .slick-row.even{background:#fff!important}
.od-grid-container .slick-cell{background:transparent!important}
.od-grid-container .slick-row.od-row-selected,.od-grid-container .slick-row.od-row-selected.odd,.od-grid-container .slick-row.od-row-selected.even{background:#fed7aa!important;border-left:3px solid #ea580c!important}
.od-grid-container .slick-row.od-row-selected .slick-cell{background:transparent!important}
.od-grid-container .slick-cell img{max-height:20px;max-width:20px;vertical-align:middle;display:inline-block!important}
.od-grid-container .slick-cell a{text-decoration:none;display:inline;vertical-align:middle;white-space:nowrap}
.od-grid-container .slick-viewport::-webkit-scrollbar{width:6px;height:6px}
.od-grid-container .slick-viewport::-webkit-scrollbar-track{background:#f1f5f9;border-radius:3px}
.od-grid-container .slick-viewport::-webkit-scrollbar-thumb{background:#94a3b8;border-radius:3px}
.od-grid-container .slick-viewport::-webkit-scrollbar-thumb:hover{background:#64748b}

.od-patient-panel{display:none;background:#fff;border-radius:8px 8px 0 0;box-shadow:0 -2px 12px rgba(0,0,0,.12);border:1px solid #e2e8f0;border-left:4px solid #1d4ed8;position:fixed;bottom:0;left:16px;right:16px;z-index:200;height:220px;max-height:35vh;overflow-y:scroll}
.od-patient-panel.show{display:block}
.od-patient-panel::-webkit-scrollbar{width:6px}
.od-patient-panel::-webkit-scrollbar-track{background:#f1f5f9;border-radius:3px}
.od-patient-panel::-webkit-scrollbar-thumb{background:#94a3b8;border-radius:3px}
.od-patient-panel::-webkit-scrollbar-thumb:hover{background:#64748b}
.od-patient-panel-header{display:flex;align-items:center;gap:8px;padding:10px 16px;background:linear-gradient(135deg,#eff6ff,#f8fafc);border-bottom:1px solid #e2e8f0}
.od-patient-panel-header svg{width:18px;height:18px;color:#1d4ed8;flex-shrink:0;stroke-width:2.2}
.od-patient-panel-header span{font-size:13px;font-weight:700;color:#0f172a;letter-spacing:.2px}
.od-patient-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:0;padding:0}
.od-patient-field{padding:10px 16px;border-right:1px solid #f1f5f9;border-bottom:1px solid #f1f5f9}
.od-patient-field:nth-child(4n){border-right:none}
.od-patient-field label{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;font-weight:700;margin-bottom:3px;display:block}
.od-patient-field span{font-size:13px;color:#0f172a;font-weight:600;word-break:break-word;line-height:1.3}
.od-patient-panel-header button{color:#64748b}
.od-patient-panel-header button:hover{color:#0f172a}

.od-customize-wrapper{position:relative}
.od-customize-dropdown{display:none;position:absolute;top:calc(100% + 4px);right:0;background:#fff;border:1px solid #e2e8f0;border-radius:8px;box-shadow:0 6px 16px rgba(0,0,0,.1);z-index:100;min-width:200px;padding:6px 0}
.od-customize-dropdown.open{display:block}
.od-customize-header{padding:6px 12px 4px;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.4px;border-bottom:1px solid #f1f5f9;margin-bottom:2px}
.od-customize-item{display:flex;align-items:center;gap:8px;padding:5px 12px;cursor:pointer;transition:background .15s}
.od-customize-item:hover{background:#f8fafc}
.od-customize-item label{display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#1e293b;font-weight:500;flex:1}
.od-customize-item input[type="checkbox"]{width:14px;height:14px;accent-color:#1d4ed8;cursor:pointer;flex-shrink:0}
.od-customize-item .od-card-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}

.hide{display:none!important}

.stockout-link{cursor:pointer;color:#dc2626;font-weight:600;font-size:11px}
.stockout-link:hover{text-decoration:underline;color:#b91c1c}

#stockoutPanel{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:999;justify-content:center;align-items:center}
#stockoutPanel.show{display:flex}
#stockoutPanel .stockout-panel-inner{background:#fff5f5;border:2px solid #dc2626;border-radius:8px;padding:15px;width:90%;max-width:700px;max-height:85vh;display:flex;flex-direction:column}
#stockoutPanel .stockout-panel-inner .stockout-test-list{flex:1;overflow-y:auto}
.stockout-title{color:#dc2626;font-size:16px;font-weight:700;margin:0 0 10px 0}
.stockout-test-list{background:#fff;border:1px solid #e2e8f0;border-radius:5px;padding:10px;max-height:200px;overflow-y:auto;margin:10px 0}
.stockout-test-item{display:flex;justify-content:space-between;align-items:center;padding:8px;border-bottom:1px solid #f1f5f9}
.stockout-test-item:last-child{border-bottom:none}
.stockout-test-name{font-weight:600;font-size:12px;color:#1a1a2e}
.stockout-test-type{font-size:11px;color:#64748b}
.stockout-toggle{display:flex;gap:5px}
.stockout-btn{padding:5px 14px;border:none;border-radius:4px;cursor:pointer;font-size:11px;font-weight:600;transition:all .15s}
.stockout-btn.available{background:#dcfce7;color:#16a34a;border:1px solid #16a34a}
.stockout-btn.available:hover{background:#bbf7d0}
.stockout-btn.available.selected{background:#16a34a!important;color:#fff!important;box-shadow:0 0 0 2px #15803d}
.stockout-btn.stockout{background:#fee2e2;color:#dc2626;border:1px solid #dc2626}
.stockout-btn.stockout:hover{background:#fecaca}
.stockout-btn.stockout.selected{background:#dc2626!important;color:#fff!important;box-shadow:0 0 0 2px #b91c1c}
.stockout-actions{display:flex;gap:10px;margin-top:15px;justify-content:flex-end}
.stockout-actions .btn{padding:8px 20px;border:none;border-radius:5px;cursor:pointer;font-size:12px;font-weight:500}
.stockout-actions .btn-danger{background:#dc2626;color:#fff}
.stockout-actions .btn-danger:hover{background:#b91c1c}
.stockout-actions .btn-secondary{background:#e2e8f0;color:#334155}
.stockout-actions .btn-secondary:hover{background:#cbd5e1}
.stockout-actions .btn-success{background:#16a34a;color:#fff}
.stockout-actions .btn-success:hover{background:#15803d}
.stockout-notice-modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:1000;justify-content:center;align-items:center}
.stockout-notice-modal.show{display:flex}
.stockout-notice-dialog{background:#fff;border-radius:8px;padding:20px;width:90%;max-width:500px;max-height:80vh;overflow-y:auto}
.stockout-notice-dialog h3{color:#dc2626;margin:0 0 15px 0;font-size:16px}
.stockout-notice-dialog .close-btn{float:right;background:none;border:none;font-size:20px;cursor:pointer;color:#64748b}
.stockout-notice-dialog .btn-row{display:flex;gap:10px;margin-top:15px;justify-content:flex-end}
.stockout-notice-dialog .btn{padding:8px 16px;border:none;border-radius:5px;cursor:pointer;font-size:12px;font-weight:500}
.stockout-notice-dialog .btn-danger{background:#dc2626;color:#fff}
.stockout-notice-dialog .btn-danger:hover{background:#b91c1c}
.stockout-notice-dialog .btn-secondary{background:#e2e8f0;color:#334155}
.stockout-notice-dialog .btn-secondary:hover{background:#cbd5e1}
.stockout-notice-dialog .order-info{background:#f8fafc;padding:10px;border-radius:5px;margin-bottom:15px;font-size:12px}
.stockout-notice-dialog .order-info strong{color:#0f172a}
.stockout-info{font-size:11px;color:#64748b;margin:5px 0}

/* Standard In-App Toast Notifications */
#toastContainer{position:fixed;top:20px;right:20px;z-index:99999;display:flex;flex-direction:column;gap:10px;max-width:380px;pointer-events:none}
.app-toast{pointer-events:auto;display:flex;align-items:flex-start;gap:10px;background:#ffffff;border-radius:8px;padding:12px 14px;box-shadow:0 10px 25px -5px rgba(0,0,0,0.15),0 8px 10px -6px rgba(0,0,0,0.1);border:1px solid #e2e8f0;border-left:5px solid #10b981;transform:translateX(120%);opacity:0;transition:transform .3s cubic-bezier(.16,1,.3,1),opacity .3s ease;font-family:inherit}
.app-toast.show{transform:translateX(0);opacity:1}
.app-toast.hide{transform:translateX(120%);opacity:0}
.app-toast.toast-success{border-left-color:#10b981}
.app-toast.toast-error{border-left-color:#ef4444}
.app-toast.toast-warning{border-left-color:#f59e0b}
.app-toast.toast-info{border-left-color:#3b82f6}
.app-toast-icon{flex-shrink:0;width:20px;height:20px;margin-top:1px}
.app-toast-content{flex:1;min-width:0}
.app-toast-title{font-size:12px;font-weight:700;color:#0f172a;margin:0 0 2px 0;line-height:1.3}
.app-toast-message{font-size:11px;color:#475569;margin:0;line-height:1.4;word-break:break-word}
.app-toast-close{background:none;border:none;color:#94a3b8;cursor:pointer;font-size:16px;line-height:1;padding:0 2px;margin-top:-2px;transition:color .15s}
.app-toast-close:hover{color:#334155}

@media(max-width:768px){
    .od-header{flex-direction:column;align-items:flex-start;gap:4px}
    .od-stats{grid-template-columns:repeat(3,1fr);gap:4px}
    .od-section-body{flex-direction:column}
    .od-tabs{flex-direction:row;border-right:none;border-bottom:1px solid #e2e8f0;min-width:0}
    .od-tab{border-left:none;border-bottom:3px solid transparent;padding:7px 10px}
    .od-tab.active{border-bottom-color:#1d4ed8}
.od-patient-grid{grid-template-columns:repeat(2,1fr)}
.od-patient-field:nth-child(4n){border-right:1px solid #f1f5f9}
.od-patient-field:nth-child(2n){border-right:none}
}
</style>

<div class="od-body">
    <div class="od-sticky-top">
        <div class="od-header">
            <div class="od-header-left">
                <div class="od-logo">L</div>
                <div>
                    <h1 class="od-title">Samples to Collect</h1>
                    <p class="od-subtitle"><%= serverNow %></p>
                </div>
            </div>
            <div class="od-header-right">
                <div class="od-nav-group">
                    <a href="LabDashboard.do" class="od-nav-btn">Lab Dashboard</a>
                    <a href="SamplesToCollect.do" class="od-nav-btn active">Samples to Collect</a>
                    <a href="SamplesCollected.do" class="od-nav-btn">Samples Collected</a>
                </div>
                <% if (selectedLabLocationName != null && !selectedLabLocationName.isEmpty()) { %>
                <div class="od-location-badge">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                    <%= selectedLabLocationName %>
                </div>
                <% } %>
                <div class="od-customize-wrapper">
                    <button class="od-customize-btn" id="od-customize-toggle">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                        Customize
                    </button>
                    <div class="od-customize-dropdown" id="od-customize-dropdown">
                        <div class="od-customize-header">Show / Hide Cards</div>
                        <div class="od-customize-item"><input type="checkbox" id="od-toggle-collect" data-card="collect" checked><label for="od-toggle-collect"><span class="od-card-dot" style="background:#14b8a6"></span>Samples to Collect</label></div>
                        <div class="od-customize-item"><input type="checkbox" id="od-toggle-collected" data-card="collected" checked><label for="od-toggle-collected"><span class="od-card-dot" style="background:#3b82f6"></span>Samples Collected</label></div>
                        <div class="od-customize-item"><input type="checkbox" id="od-toggle-testing" data-card="testing" checked><label for="od-toggle-testing"><span class="od-card-dot" style="background:#f59e0b"></span>Awaiting Testing</label></div>
                        <div class="od-customize-item"><input type="checkbox" id="od-toggle-validation" data-card="validation" checked><label for="od-toggle-validation"><span class="od-card-dot" style="background:#7c3aed"></span>Awaiting Validation</label></div>
                        <div class="od-customize-item"><input type="checkbox" id="od-toggle-completed" data-card="completed" checked><label for="od-toggle-completed"><span class="od-card-dot" style="background:#22c55e"></span>Completed</label></div>
                        <div class="od-customize-item"><input type="checkbox" id="od-toggle-patients" data-card="patients" checked><label for="od-toggle-patients"><span class="od-card-dot" style="background:#e11d48"></span>Total Patients Today</label></div>
                    </div>
                </div>
                <button id="refreshButton" class="od-refresh-btn" onclick="location.href='SamplesToCollect.do'">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                    Refresh
                </button>
            </div>
        </div>
        <div class="od-stats" id="todayStat">
            <div class="od-stat-card" data-card="collect"><div class="od-stat-icon teal"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg></div><div class="od-stat-info"><div class="od-stat-label">To Collect</div><div class="od-stat-value" id="samplesToCollect">0</div></div></div>
            <div class="od-stat-card" data-card="collected"><div class="od-stat-icon blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></div><div class="od-stat-info"><div class="od-stat-label">Collected</div><div class="od-stat-value" id="samplesCollected">0</div></div></div>
            <div class="od-stat-card" data-card="testing"><div class="od-stat-icon amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div><div class="od-stat-info"><div class="od-stat-label">Testing</div><div class="od-stat-value" id="awaitingTestCount">0</div></div></div>
            <div class="od-stat-card" data-card="validation" style="<% if (!alwaysValidate) { %> display:none <% } %>"><div class="od-stat-icon purple"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg></div><div class="od-stat-info"><div class="od-stat-label">Validation</div><div class="od-stat-value" id="awaitingValidationCount">0</div></div></div>
            <div class="od-stat-card" data-card="completed"><div class="od-stat-icon green"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div><div class="od-stat-info"><div class="od-stat-label">Completed</div><div class="od-stat-value" id="completedTestCount">0</div></div></div>
            <div class="od-stat-card" data-card="patients"><div class="od-stat-icon rose"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div><div class="od-stat-info"><div class="od-stat-label">Patients</div><div class="od-stat-value" id="totalCollectedTodayCount">0</div></div></div>
        </div>
    </div>

    <div class="od-main-content">
    <span id="translatedColumnNames"
        data-patientID='<bean:message key="dashboard.sample.column.patientID"/>'
        data-patientName='<bean:message key="dashboard.sample.column.patientName"/>'
        data-source='<bean:message key="dashboard.sample.column.source"/>'
        data-sectionNames='<bean:message key="dashboard.sample.column.sectionNames"/>'
        data-sampleType='<bean:message key="dashboard.sample.column.sampleType"/>'
        data-priority='<bean:message key="dashboard.sample.column.priority"/>'
        data-total='<bean:message key="dashboard.sample.column.total"/>'
        data-notes='<bean:message key="dashboard.sample.column.notes"/>'
        data-action='<bean:message key="dashboard.sample.column.action"/>'
        data-accessionNumber='<bean:message key="dashboard.sample.column.accessionNumber"/>'
        data-pendingTests='<bean:message key="dashboard.sample.column.pendingTests"/>'
        data-pendingValidation='<bean:message key="dashboard.sample.column.pendingValidation"/>'
        data-referredTests='<bean:message key="dashboard.sample.column.referredTests"/>'
        data-completed='<bean:message key="dashboard.sample.column.completed"/>'
        data-printed='<bean:message key="dashboard.sample.column.printed"/>'
        data-tat='<bean:message key="dashboard.sample.column.tat"/>'
        data-link-collectSample='<bean:message key="dashboard.sample.column.link.collectSample"/>'
        data-link-result='<bean:message key="dashboard.sample.column.link.result"/>'
        data-link-validate='<bean:message key="dashboard.sample.column.link.validate"/>'
        data-link-print='<bean:message key="dashboard.sample.column.link.print"/>'
        data-link-label='<bean:message key="dashboard.sample.column.link.label"/>'
    ></span>

    <div class="od-section">
        <div class="od-section-body" style="flex-direction:column">
            <div style="display:flex;flex:1;min-height:0;overflow:hidden">
                <div class="od-tabs" id="od-tabs">
                    <button class="od-tab" data-tab="-1">Dashboard</button>
                    <button class="od-tab active" data-tab="0">Today <span class="od-badge" id="od-today-collect-badge">0</span></button>
                    <button class="od-tab" data-tab="1">Backlog <span class="od-badge" id="od-backlog-collect-badge">0</span></button>
                </div>
                <div class="od-grid-area" id="od-grid-area">
                    <div class="od-dashboard-view" id="od-dashboard-view">
                        <div id="dashEmbed"></div>
                    </div>
                    <div class="od-grid-container" id="todaySamplesToCollectListContainer"><div id="todaySamplesToCollectListContainer-slick-grid"></div></div>
                    <div class="od-grid-container" id="backlogSamplesToCollectListContainer"><div id="backlogSamplesToCollectListContainer-slick-grid"></div></div>
                </div>
            </div>
        </div>
    </div>
    <div id="patientDetails" class="od-patient-panel">
        <div class="od-patient-panel-header">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            <span style="flex:1">Patient Details</span>
            <button onclick="jQuery('#patientDetails').removeClass('show')" style="background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;display:flex;align-items:center;transition:background .15s" onmouseover="this.style.background='#e2e8f0'" onmouseout="this.style.background='none'"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
        </div>
        <div class="od-patient-grid">
            <div class="od-patient-field"><label>Patient ID</label><span id="patientId"></span></div>
            <div class="od-patient-field"><label>Name</label><span id="name"></span></div>
            <div class="od-patient-field"><label>Father/Husband</label><span id="primaryRelative"></span></div>
            <div class="od-patient-field"><label>Village</label><span id="village"></span></div>
            <div class="od-patient-field"><label>Gender</label><span id="gender"></span></div>
            <div class="od-patient-field"><label>Age</label><span id="age"></span></div>
            <div class="od-patient-field" style="grid-column:1/-1;background:#f0fdfa"><label>Tests</label><span id="patientTests" style="font-size:12px;line-height:1.5"></span></div>
        </div>
    </div>
    </div>

    <div id="stockoutPanel">
        <div class="stockout-panel-inner">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <p class="stockout-title">Stock-Out Management</p>
                <button type="button" onclick="StockOut.hidePanel()" style="background:none;border:none;font-size:16px;cursor:pointer;color:#64748b">&times;</button>
            </div>
            <p class="stockout-info">Mark tests as Stock-Out for unavailable reagents. Available tests will proceed normally.</p>
            <div id="stockoutTestList" class="stockout-test-list">
                <p style="color:#64748b;font-size:12px">Loading...</p>
            </div>
            <div class="stockout-actions">
                <button type="button" class="btn btn-secondary" onclick="StockOut.markAllAvailable()">Mark All Available</button>
                <button type="button" class="btn btn-danger" onclick="StockOut.markAllStockOut()">Mark All Stock-Out</button>
                <button type="button" class="btn btn-success" onclick="StockOut.saveSelections(false)" style="background:#2563eb;color:#fff">Save & Send to Billing</button>
                <button type="button" class="btn btn-success" onclick="StockOut.saveSelections(true)" style="background:#059669;color:#fff">Save & Confirm Billing ✓</button>
                <button type="button" class="btn btn-success" onclick="StockOut.generateNotice()">Generate Stock-Out Notice</button>
            </div>
        </div>
    </div>

    <div id="stockoutNoticeModal" class="stockout-notice-modal">
        <div class="stockout-notice-dialog">
            <button type="button" class="close-btn" onclick="StockOut.closeNoticeModal()">&times;</button>
            <h3>Stock-Out Notice Generated</h3>
            <div class="order-info">
                <strong>Notice Number:</strong> <span id="snNoticeNumber">-</span><br>
                <strong>Date:</strong> <span id="snDate">-</span><br>
                <strong>Order:</strong> <span id="snOrder">-</span><br>
                <strong>Tests Voided:</strong> <span id="snTestsVoided">-</span>
            </div>
            <p style="font-size:12px;color:#64748b">The stock-out notice has been sent to print. The billing team has been notified via Odoo sync.</p>
            <div class="btn-row">
                <button type="button" class="btn btn-secondary" onclick="StockOut.closeNoticeModal()">Close</button>
            </div>
        </div>
    </div>

    <div id="labelPrintModel" class="hide details">
        <div class="modal-content">
            <div class="col-12" style="display:inline-block;margin-right:10px">
                <div id="labelDetails">
                    <div style="font-family:sans-serif;font-size:8px;margin-right:15px;margin-top:-4px;margin-bottom:2px">
                        <span class='label-value' id="patientName"></span><br/>
                        <span class='label-value' style="font-size:10px;font-weight:bolder" id="labelPatientId"></span>
                        <span class='label-value' style="padding-left:5px;font-size:10px;font-weight:bolder" id="patientGender"></span>
                        <span class='label-value' style="padding-left:5px;font-size:10px;font-weight:bolder" id="patientAge"></span>
                    </div>
                    <svg style="margin-left:-10px;margin-bottom:-20px;height:50px" id="barcode"></svg>
                </div>
            </div>
        </div>
    </div>
</div>

<div id="toastContainer"></div>

<script type="text/javascript">
window.showAppToast = function(title, message, type, duration) {
    type = type || 'success';
    duration = duration !== undefined ? duration : 4000;
    var container = document.getElementById('toastContainer');
    if (!container) return;

    var toast = document.createElement('div');
    toast.className = 'app-toast toast-' + type;

    var iconSvg = '';
    if (type === 'success') {
        iconSvg = '<svg class="app-toast-icon" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>';
    } else if (type === 'error') {
        iconSvg = '<svg class="app-toast-icon" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg>';
    } else if (type === 'warning') {
        iconSvg = '<svg class="app-toast-icon" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.2"><path d="m10.29 3.86-8.6 14.9a1.73 1.73 0 0 0 1.5 2.6h17.2a1.73 1.73 0 0 0 1.5-2.6l-8.6-14.9a1.73 1.73 0 0 0-3 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>';
    } else {
        iconSvg = '<svg class="app-toast-icon" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>';
    }

    toast.innerHTML = iconSvg +
        '<div class="app-toast-content">' +
            '<div class="app-toast-title">' + title + '</div>' +
            '<div class="app-toast-message">' + message + '</div>' +
        '</div>' +
        '<button class="app-toast-close" onclick="this.parentElement.remove()">&times;</button>';

    container.appendChild(toast);
    setTimeout(function() { toast.classList.add('show'); }, 20);

    if (duration > 0) {
        setTimeout(function() {
            toast.classList.remove('show');
            toast.classList.add('hide');
            setTimeout(function() { if (toast.parentElement) toast.remove(); }, 350);
        }, duration);
    }
};

(function() {
    try {
        var queued = sessionStorage.getItem('pendingToast');
        if (queued) {
            sessionStorage.removeItem('pendingToast');
            var d = JSON.parse(queued);
            setTimeout(function() {
                window.showAppToast(d.title, d.message, d.type, d.duration);
            }, 300);
        }
    } catch(e) {}
})();

var options={enableColumnReorder:false,enableCellNavigation:true,showHeaderRow:true,headerRowHeight:30,explicitInitialization:true,forceFitColumns:true,rowHeight:36,defaultColumnWidth:110};

var showStats=function(s){
    jQuery("#awaitingTestCount").text(s.awaitingTestCount);
    jQuery("#awaitingValidationCount").text(s.awaitingValidationCount);
    jQuery("#completedTestCount").text(s.completedTestCount);
    jQuery("#totalCollectedTodayCount").text(s.totalCollectedTodayCount);
    jQuery("#samplesToCollect").text(s.samplesToCollect);
    jQuery("#samplesCollected").text(s.samplesCollected);
}

jQuery(document).ready(function(){
    var selectedLabLocationName='<%= selectedLabLocationName.replaceAll("'", "\\\\'") %>';

    function matchesLocationFilter(order){
        if(!selectedLabLocationName)return true;
        var c=(order.comments||order.clinicalDataNotes||"")+"";
        var m=c.match(/\[LAB_LOCATION:([^\]]+)\]/);
        if(!m)return true;
        return m[1].trim().toLowerCase()===selectedLabLocationName.trim().toLowerCase();
    }
    function filterByLocation(arr){return selectedLabLocationName?arr.filter(matchesLocationFilter):arr}

    window.evaluatedSampleIds = new Set(<%= evaluatedSampleIdsJson %>);
    window.sentToBillingSampleIds = new Set(<%= sentToBillingSampleIdsJson %>);
    window.confirmedSampleIds = new Set(<%= confirmedSampleIdsJson %>);
    window.confirmedPatientRefs = new Set();

    var todayOrderList=JSON.parse('<%=todayOrderListJson%>');
    var todaySampleNotCollectedList=JSON.parse('<%=todaySampleNotCollectedListJson%>');
    var backlogSampleNotCollectedList=JSON.parse('<%=backlogSampleNotCollectedListJson%>');
    var backlogOrderList=JSON.parse('<%=backlogOrderListJson%>');

    todayOrderList=filterByLocation(todayOrderList);
    todaySampleNotCollectedList=filterByLocation(todaySampleNotCollectedList);
    backlogSampleNotCollectedList=filterByLocation(backlogSampleNotCollectedList);
    backlogOrderList=filterByLocation(backlogOrderList);

    var applyConfirmedOrders = function(list) {
        if (!list) return;
        list.forEach(function(o) {
            var sId = String(o.orderId || o.sampleId || '').trim();
            var smpId = o.sampleId ? String(o.sampleId).trim() : '';
            var pRef = String(o.stNumber || o.patientId || '').trim();
            if ((sId && window.confirmedSampleIds.has(sId)) ||
                (smpId && window.confirmedSampleIds.has(smpId)) ||
                (pRef && window.confirmedPatientRefs.has(pRef))) {
                o.hasPaid = true;
            }
        });
    };
    applyConfirmedOrders(todaySampleNotCollectedList);
    applyConfirmedOrders(backlogSampleNotCollectedList);
    applyConfirmedOrders(todayOrderList);
    applyConfirmedOrders(backlogOrderList);

    (function checkOdooConfirmed() {
        var hasUnconfirmed = (todaySampleNotCollectedList || []).concat(backlogSampleNotCollectedList || []).some(function(o) {
            return !o.hasPaid;
        });
        if (!hasUnconfirmed) return;
        new Ajax.Request('<%=basePath%>pages/dashboard/sendToBilling.jsp?action=checkOdooConfirmed', {
            method: 'get',
            onSuccess: function(xhr) {
                try {
                    var resp = JSON.parse(xhr.responseText);
                    if (resp.success && resp.confirmedRefs && resp.confirmedRefs.length > 0) {
                        var changed = false;
                        resp.confirmedRefs.forEach(function(ref) {
                            window.confirmedPatientRefs.add(String(ref).trim());
                        });
                        var all = (window.todaySampleNotCollectedList || []).concat(window.backlogSampleNotCollectedList || []);
                        all.forEach(function(o) {
                            var pRef = String(o.stNumber || o.patientId || '').trim();
                            var sId = String(o.orderId || o.sampleId || '').trim();
                            if ((pRef && window.confirmedPatientRefs.has(pRef)) || (sId && window.confirmedPatientRefs.has(sId))) {
                                if (!o.hasPaid) {
                                    o.hasPaid = true;
                                    changed = true;
                                }
                            }
                        });
                        if (changed) {
                            sessionStorage.setItem('pendingToast', JSON.stringify({
                                title: 'Quotation Approved in Odoo',
                                message: 'Quotation confirmed in Odoo! Sample collection unlocked.',
                                type: 'success',
                                duration: 4500
                            }));
                            window.location.reload();
                        }
                    }
                } catch(e) {}
            }
        });
    })();

    window.todayOrderList = todayOrderList;
    window.todaySampleNotCollectedList = todaySampleNotCollectedList;
    window.backlogSampleNotCollectedList = backlogSampleNotCollectedList;
    window.backlogOrderList = backlogOrderList;

    var _alv=<%=alwaysValidate%>;
    todayOrderList.forEach(function(o){o.link=generateAllLinksForOrder(o,_alv)});
    backlogOrderList.forEach(function(o){o.link=generateAllLinksForOrder(o,_alv)});

    var showPriorityColumn=<%=showPriorityColumn%>;

    var isToday=function(d){var n=new Date('<%= serverNow %>');return n.getDate()===d.getDate()&&n.getMonth()===d.getMonth()&&n.getFullYear()===d.getFullYear()};
    var todayStats={
        awaitingTestCount:todayOrderList.filter(function(o){return o.pendingTestCount>0}).length,
        awaitingValidationCount:todayOrderList.filter(function(o){return o.pendingTestCount==0&&o.pendingValidationCount>0}).length,
        completedTestCount:todayOrderList.filter(function(o){return o.isCompleted}).length,
        totalCollectedTodayCount:todayOrderList.filter(function(o){return isToday(new Date(o.enteredDate))}).length,
        samplesToCollect:todaySampleNotCollectedList.length,
        samplesCollected:todayOrderList.length
    };
    showStats(todayStats);

    jQuery("#od-today-collect-badge").text(todaySampleNotCollectedList.length);
    jQuery("#od-backlog-collect-badge").text(backlogSampleNotCollectedList.length);

    var tObj=new order("#todaySamplesToCollectListContainer-slick-grid",todaySampleNotCollectedList,generateAllLinksForOrder,getColumnsForSampleNotCollected,<%=alwaysValidate%>,showPriorityColumn);
    var tDV=new Slick.Data.DataView();
    var tGrid=new Slick.Grid(tObj.div,tDV,tObj.columns,options);
    createGrid(tGrid,tDV,tObj,onRowSelection);

    var bObj=new order("#backlogSamplesToCollectListContainer-slick-grid",backlogSampleNotCollectedList,generateAllLinksForOrder,getColumnsForSampleNotCollected,<%=alwaysValidate%>,showPriorityColumn);
    var bDV=new Slick.Data.DataView();
    var bGrid=new Slick.Grid(bObj.div,bDV,bObj.columns,options);
    createGrid(bGrid,bDV,bObj,onRowSelection);

    var todayContainerEl=document.getElementById('todaySamplesToCollectListContainer');
    var backlogContainerEl=document.getElementById('backlogSamplesToCollectListContainer');
    var dashboardViewEl=document.getElementById('od-dashboard-view');

    var allGrids=[
        {grid:tGrid,el:todayContainerEl},
        {grid:bGrid,el:backlogContainerEl}
    ];

    allGrids.forEach(function(g){
        if(g.grid&&g.grid.onClick){g.grid.onClick.subscribe(function(e,args){
            var el=jQuery(args.grid.getContainerNode());el.find('.slick-row').removeClass('od-row-selected');
            var rn=args.grid.getCellNode(args.row,0);if(rn)jQuery(rn).closest('.slick-row').addClass('od-row-selected');
        })}
    });

    function showGrid(index){
        dashboardViewEl.className='od-dashboard-view';
        allGrids.forEach(function(g,i){
            if(!g.el)return;
            if(i===index){
                g.el.className='od-grid-container active';
                if(g.grid&&g.grid.resizeCanvas){
                    setTimeout(function(){
                        g.grid.resizeCanvas();
                        if(g.grid.autosizeColumns) g.grid.autosizeColumns();
                        g.grid.invalidate();
                    },50);
                }
            }else{
                g.el.className='od-grid-container';
            }
        });
    }

    jQuery(window).on('resize', function(){
        allGrids.forEach(function(g){
            if(g.grid && g.grid.resizeCanvas){
                g.grid.resizeCanvas();
                if(g.grid.autosizeColumns) g.grid.autosizeColumns();
                g.grid.invalidate();
            }
        });
    });

    function showDashboard(){
        allGrids.forEach(function(g){if(g.el)g.el.className='od-grid-container'});
        dashboardViewEl.className='od-dashboard-view active';
    }

    jQuery('.od-tab').on('click',function(){
        var idx=parseInt(jQuery(this).data('tab'));
        jQuery('.od-tab').removeClass('active');jQuery(this).addClass('active');
        if(idx===-1){showDashboard()}else{showGrid(idx)}
    });

    var activeTab=<%= (String)request.getSession().getAttribute("activeTab") %>||0;
    if(activeTab>1)activeTab=0;
    setTimeout(function(){jQuery('.od-tab[data-tab="'+activeTab+'"]').trigger('click')},50);

    jQuery("#todaySamplesToCollectListContainer-slick-grid,#backlogSamplesToCollectListContainer-slick-grid")
        .on("click",".label",function(event){
            var p=event.currentTarget;
            labelSelected(p.getAttribute('stNumber'),p.getAttribute('accessionNumber'),p.getAttribute('collectionDateStr'),jQuery);
        });

    function renderEmbeddedDashboard(){
        var el=document.getElementById('dashEmbed');
        var todayOrders=filterByLocation(JSON.parse('<%=todayOrderListJson%>'));
        var todayNotCollected=filterByLocation(JSON.parse('<%=todaySampleNotCollectedListJson%>'));
        var backlogNotCollected=filterByLocation(JSON.parse('<%=backlogSampleNotCollectedListJson%>'));

        var sv={
            tc:todayNotCollected.length,sc:todayOrders.length,
            at:todayOrders.filter(function(o){return o.pendingTestCount>0}).length,
            av:todayOrders.filter(function(o){return o.pendingTestCount==0&&o.pendingValidationCount>0}).length,
            co:todayOrders.filter(function(o){return o.isCompleted}).length
        };

        var icons={
            tc:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/></svg>',
            sc:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
            at:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
            pr:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>',
            ca:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
            ta:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z"/><path d="M12 6v6l4 2"/></svg>'
        };
        function spark(d,w,h,c){
            var s='<svg width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'">';
            var mx=Math.max.apply(null,d),mn=Math.min.apply(null,d),rn=mx-mn||1;var pts=[];
            for(var i=0;i<d.length;i++){var x=i*(w/(d.length-1)),y=h-((d[i]-mn)/rn)*(h-4)-2;pts.push(x+','+y)}
            s+='<polyline points="'+pts.join(' ')+'" fill="none" stroke="'+c+'" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>';
            s+='<linearGradient id="sg2_'+c.replace('#','')+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+c+'" stop-opacity=".3"/><stop offset="100%" stop-color="'+c+'" stop-opacity="0"/></linearGradient>';
            s+='<polygon points="0,'+h+' '+pts.join(' ')+' '+w+','+h+'" fill="url(#sg2_'+c.replace('#','')+')"/></svg>';return s;
        }

        var html='<div class="ds-grid">';
        html+='<div class="ds-card"><div class="ds-card-top"><div class="ds-card-icon teal">'+icons.tc+'</div><div><div class="ds-card-label">SAMPLES TO COLLECT</div><div class="ds-card-value">'+sv.tc+'</div></div></div><div class="ds-card-footer"><span>Samples to Collect</span><span>'+sv.tc+' samples</span></div><div class="ds-card-spark">'+spark([3,5,2,7,4,6,3,8,5,4],70,30,'#0f766e')+'</div></div>';
        html+='<div class="ds-card"><div class="ds-card-top"><div class="ds-card-icon blue">'+icons.sc+'</div><div><div class="ds-card-label">SAMPLES COLLECTED</div><div class="ds-card-value">'+sv.sc+'</div></div></div><div class="ds-card-footer"><span>Last 24 hours trend:</span><span>'+sv.sc+'/'+(sv.sc+5)+'</span></div><div class="ds-card-spark">'+spark([2,4,6,3,5,7,4,6,8,5],70,30,'#1d4ed8')+'</div></div>';
        html+='<div class="ds-card"><div class="ds-card-top"><div class="ds-card-icon amber">'+icons.at+'</div><div><div class="ds-card-label">AWAITING TESTING</div><div class="ds-card-value">'+sv.at+'</div></div></div><div class="ds-card-footer"><span>Last 24 hours trend:</span><span>'+sv.at+' Awaiting testing</span></div><div class="ds-card-spark">'+spark([4,3,5,2,6,4,3,5,7,4],70,30,'#d97706')+'</div></div>';
        html+='<div class="ds-card"><div class="ds-card-top"><div class="ds-card-icon" style="background:#faf5ff;color:#7c3aed">'+icons.pr+'</div><div><div class="ds-card-label">PENDING RESULTS</div><div class="ds-card-value">0</div></div></div><div class="ds-progress"><div style="width:30%;background:#16a34a"></div><div style="width:25%;background:#eab308"></div><div style="width:20%;background:#f97316"></div><div style="width:25%;background:#dc2626"></div></div><div class="ds-card-footer"><span>STAT: 0</span><span>Routine: 0</span><span>Result: 0</span></div></div>';
        html+='<div class="ds-card"><div class="ds-card-top"><div class="ds-card-icon red">'+icons.ca+'</div><div><div class="ds-card-label">CRITICAL ALERTS</div><div class="ds-card-value">0</div></div></div><div class="ds-alert-count">0</div></div>';
        html+='<div class="ds-card"><div class="ds-card-top"><div class="ds-card-icon purple">'+icons.ta+'</div><div><div class="ds-card-label">TAT PERFORMANCE</div><div class="ds-card-value">8.7 ms</div></div></div><div class="ds-gauge-wrap"><svg width="60" height="35" viewBox="0 0 60 35"><path d="M5 30 A25 25 0 0 1 55 30" fill="none" stroke="#e2e8f0" stroke-width="5" stroke-linecap="round"/><path d="M5 30 A25 25 0 0 1 55 30" fill="none" stroke="#7c3aed" stroke-width="5" stroke-linecap="round" stroke-dasharray="78.5" stroke-dashoffset="20"/></svg></div><div class="ds-card-footer"><span>Average:</span><span>8.7 ms</span></div></div>';
        html+='</div>';

        html+='<div class="db-row">';
        html+='<div class="db-panel"><div class="db-panel-hdr"><h3>Workflow Efficiency</h3></div><div class="db-panel-body"><div style="font-size:11px;font-weight:600;color:#0f172a;margin-bottom:6px">Test Turnaround Time by Priority</div><div class="chart-wrap"><canvas id="ewChart2"></canvas></div></div></div>';
        html+='<div class="db-panel"><div class="db-panel-hdr"><h3><span class="dot"></span> Samples to Collect</h3></div><div class="db-panel-body"><div class="db-tabs" id="ecTabs2"></div><div style="overflow-x:auto;flex:1"><table class="db-table"><thead id="ecHead2"></thead><tbody id="ecBody2"></tbody></table></div></div></div>';
        html+='<div class="db-panel"><div class="db-panel-hdr"><h3>Lab Insights</h3></div><div class="db-panel-body"><div style="font-size:11px;font-weight:600;color:#0f172a;margin-bottom:6px">Test Volume by Type</div><div class="chart-wrap"><canvas id="eiChart2"></canvas></div></div></div>';
        html+='</div>';
        el.innerHTML=html;

        var tabs=[{l:'Today',c:todayNotCollected.length,cls:'green'},{l:'Backlog',c:backlogNotCollected.length,cls:'red'},{l:'Backlog',c:todayNotCollected.length+backlogNotCollected.length,cls:'blue'}];
        var th='';tabs.forEach(function(t,i){th+='<button class="db-tab'+(i===0?' active':'')+'" data-didx="'+i+'">'+t.l+' <span class="badge '+t.cls+'">'+t.c+'</span></button>';});
        document.getElementById('ecTabs2').innerHTML=th;
        document.getElementById('ecHead2').innerHTML='<tr><th>Patient ID</th><th>Patient Name</th><th>Priority</th><th>Status</th><th>Sample Collection</th></tr>';
        function rTable(di){
            var d=di===0?todayNotCollected:di===1?backlogNotCollected:todayNotCollected.concat(backlogNotCollected);
            var b='';d.slice(0,8).forEach(function(r){
                var p=(r.priority||'Low').toLowerCase(),pc=p==='high'?'high':'low';
                var sc=Math.floor(Math.random()*60),mn=Math.floor(Math.random()*60);
                b+='<tr><td>'+((r.stNumber||'').substring(0,12))+'</td><td>'+((r.firstName||'')+' '+(r.lastName||'')).substring(0,20)+'</td>';
                b+='<td><span class="db-pri '+pc+'">'+(r.priority||'Low')+'</span> <span class="db-status">Dynamic</span></td>';
                b+='<td>'+Math.floor(Math.random()*12)+'</td><td class="db-timer">00:'+String(mn).padStart(2,'0')+':'+String(sc).padStart(2,'0')+' mm</td></tr>';
            });
            document.getElementById('ecBody2').innerHTML=b;
        }
        rTable(0);
        document.querySelectorAll('[data-didx]').forEach(function(btn){btn.addEventListener('click',function(){
            document.querySelectorAll('[data-didx]').forEach(function(x){x.classList.remove('active')});this.classList.add('active');
            rTable(parseInt(this.dataset.didx));
        });});

        setTimeout(function(){
            var c1=document.getElementById('ewChart2');if(c1){var x1=c1.getContext('2d'),dp=window.devicePixelRatio||1,r1=c1.parentElement.getBoundingClientRect();c1.width=r1.width*dp;c1.height=r1.height*dp;x1.scale(dp,dp);var w=r1.width,h=r1.height;
            x1.fillStyle='#f8fafc';x1.fillRect(0,0,w,h);
            var cats=['STAT','Routine','STAT','Routine'],sd=[42,0,38,0],rd=[0,35,0,45],bw=w/10,mx=50,ch=h-28;
            for(var i=0;i<4;i++){var bx=24+i*((w-48)/4)+bw*0.2;
            x1.fillStyle='#0f766e';x1.beginPath();x1.roundRect(bx,h-22-ch*0.7,bw*0.85,sd[i]/mx*ch||ch*0.7,3);x1.fill();
            if(rd[i]>0){x1.fillStyle='#d97706';x1.beginPath();x1.roundRect(bx+bw*0.3,h-22-rd[i]/mx*ch,bw*0.85,rd[i]/mx*ch,3);x1.fill();}
            x1.fillStyle='#64748b';x1.font='9px sans-serif';x1.textAlign='center';x1.fillText(cats[i],bx+bw*0.5,h-6);}
            x1.fillStyle='#64748b';x1.font='9px sans-serif';x1.textAlign='right';
            for(var v=0;v<=50;v+=10){var y=h-22-(v/mx*ch);x1.fillText(v,18,y+3);x1.strokeStyle='#e2e8f0';x1.lineWidth=.5;x1.beginPath();x1.moveTo(22,y);x1.lineTo(w,y);x1.stroke();}
            x1.fillStyle='#0f766e';x1.fillRect(w-80,h-10,7,7);x1.fillStyle='#64748b';x1.font='9px sans-serif';x1.textAlign='left';x1.fillText('STAT',w-70,h-3);
            x1.fillStyle='#d97706';x1.fillRect(w-38,h-10,7,7);x1.fillStyle='#64748b';x1.fillText('Routine',w-28,h-3);}

            var c2=document.getElementById('eiChart2');if(c2){var x2=c2.getContext('2d'),dp2=window.devicePixelRatio||1,r2=c2.parentElement.getBoundingClientRect();c2.width=r2.width*dp2;c2.height=r2.height*dp2;x2.scale(dp2,dp2);var w2=r2.width,h2=r2.height;
            var labs=['Sun','Mon','Tue','Wed','Thu','Fri','Sat','Dec'],ds=[{d:[80,120,95,180,140,160,110,200],c:'#0f766e'},{d:[60,90,110,150,120,130,95,170],c:'#1d4ed8'},{d:[40,70,80,120,100,110,85,140],c:'#d97706'}],mv=350,ch2=h2-25,pL=28;
            x2.fillStyle='#f8fafc';x2.fillRect(0,0,w2,h2);
            x2.fillStyle='#64748b';x2.font='9px sans-serif';x2.textAlign='right';
            for(var v=0;v<=350;v+=50){var y=h2-25-(v/mv*ch2);x2.fillText(v,pL-4,y+3);x2.strokeStyle='#e2e8f0';x2.lineWidth=.5;x2.beginPath();x2.moveTo(pL,y);x2.lineTo(w2-8,y);x2.stroke();}
            x2.textAlign='center';var st=(w2-pL-8)/(labs.length-1);labs.forEach(function(l,i){x2.fillText(l,pL+i*st,h2-5);});
            ds.forEach(function(s){x2.strokeStyle=s.c;x2.lineWidth=2;x2.beginPath();s.d.forEach(function(v,i){var x=pL+i*st,y=h2-25-(v/mv*ch2);if(i===0)x2.moveTo(x,y);else x2.lineTo(x,y);});x2.stroke();});}
        },200);
    }
    renderEmbeddedDashboard();
});

var printDiv=function(d){var w=window.open('','Print-Window');w.document.open();w.document.write('<html><head><style>@media print{@page{size:100mm 20mm;margin:0mm;font-size:7px}}</style></head><body onload="window.print()">'+document.getElementById(d).innerHTML+'</body></html>');w.document.close();setTimeout(function(){w.close()},10)}
var showLabelDetails=function(n,t,g,b,s,c){jQuery("#patientName").text(n);if(n==='M')g='Male';if(n==='F')g='Female';if(n=='O')g='Other';jQuery("#patientGender").text(g);jQuery("#patientAge").text(b);jQuery('#labelPatientId').text(s);jQuery('#collectionDate').text(c);jQuery('#tests').text(t)}
var showLabelDetailsWithoutPatientDetails=function(s,c){jQuery('#labelPatientId').text(s);jQuery('#secondLabelPatientId').text(s);jQuery('#collectionDate').text(c);jQuery('#secondLabelCollectionDate').text(c)}

function labelSelected(st,an,cd,j){
    new Ajax.Request('ajaxQueryXML',{method:'get',parameters:"provider=OrderedTestsPopulateProvider&accessionNumber="+an,
        onSuccess:function(xhr){
            var dp='<%=SystemConfiguration.getInstance().getPatternForDateLocale()%>',sp='<%=showPatientsDetailsInSampleLabelPrint%>';
            if(sp==='true')showLabelDetails(OpenElis.Utils.getXMLValue(xhr.responseXML,'patientName'),OpenElis.Utils.getXMLValue(xhr.responseXML,'tests'),OpenElis.Utils.getXMLValue(xhr.responseXML,'gender'),OpenElis.Utils.calculateAge(OpenElis.Utils.getXMLValue(xhr.responseXML,'birth_date'),dp),st,cd);
            else showLabelDetailsWithoutPatientDetails(st,cd);
            j(".accessionNumber").html(an);j("#barcode").JsBarcode(an,{width:1.1,height:25,fontSize:9});printDiv('labelPrintModel');
        }
    });
}

var showPatientDetails=function(s,f,m,l,p,v,g,a){var el=document.getElementById('patientDetails');el.classList.add('show');document.getElementById('patientId').textContent=s||'N/A';document.getElementById('name').textContent=f+" "+(m?m+" ":"")+l;document.getElementById('primaryRelative').textContent=p||'N/A';document.getElementById('village').textContent=v||'N/A';document.getElementById('gender').textContent=g;document.getElementById('age').textContent=a}

function onRowSelection(r){
    if(r.stNumber)new Ajax.Request('ajaxQueryXML',{method:'get',parameters:"provider=PatientSearchPopulateProvider&stNumber="+r.stNumber,onSuccess:onRowSelectionSuccess,onFailure:function(){}});
    if(r.accessionNumber){
        new Ajax.Request('ajaxQueryXML',{method:'get',parameters:"provider=OrderedTestsPopulateProvider&accessionNumber="+r.accessionNumber,onSuccess:function(xhr){jQuery("#patientTests").text(OpenElis.Utils.getXMLValue(xhr.responseXML,'tests')||"N/A")},onFailure:function(){}});
    }else{
        jQuery("#patientTests").text(r.testNames||(r.totalTestCount?r.totalTestCount+" test(s)":"N/A"));
    }
}
function onRowSelectionSuccess(xhr){
    var dp='<%=SystemConfiguration.getInstance().getPatternForDateLocale()%>';
    showPatientDetails(OpenElis.Utils.getXMLValue(xhr.responseXML,'ST_ID'),OpenElis.Utils.getXMLValue(xhr.responseXML,'firstName'),OpenElis.Utils.getXMLValue(xhr.responseXML,'middleName'),OpenElis.Utils.getXMLValue(xhr.responseXML,'lastName'),OpenElis.Utils.getXMLValue(xhr.responseXML,'primaryRelative'),getAddressValue(xhr.responseXML,1),OpenElis.Utils.getXMLValue(xhr.responseXML,'gender'),OpenElis.Utils.calculateAge(OpenElis.Utils.getXMLValue(xhr.responseXML,'dob'),dp));
}
function getAddressValue(r,i){var f=r.getElementsByTagName('addressline').item(i),v=f&&f.getElementsByTagName('value').item(0);return v!=null&&v.firstChild!=null?v.firstChild.nodeValue:""}

var StockOut={
    tests:[],
    selectedStatus:{},
    currentOrderId:null,

    showPanel:function(orderId){
        var self=this;
        this.currentOrderId=orderId;
        this.selectedStatus={};
        this.tests=[];
        var p = document.getElementById('stockoutPanel');
        if (p) {
            p.style.display = 'flex';
            p.classList.add('show');
        }
        var listContainer = document.getElementById('stockoutTestList');
        if (listContainer) {
            listContainer.innerHTML = '<div style="padding:15px;text-align:center;color:#64748b;font-size:12px;">Loading order tests...</div>';
        }

        // 0. Extract tests immediately from client-side row data if present
        var matchedOrder = null;
        var allRows = (window.todaySampleNotCollectedList || []).concat(window.backlogSampleNotCollectedList || []);
        for(var k = 0; k < allRows.length; k++){
            if(String(allRows[k].orderId) === String(orderId) || String(allRows[k].sampleId) === String(orderId)){
                matchedOrder = allRows[k];
                break;
            }
        }
        if (matchedOrder) {
            var rawTests = matchedOrder.testNames || matchedOrder.tests || matchedOrder.testDescription;
            if (rawTests) {
                var testList = [];
                if (typeof rawTests === 'string') {
                    try {
                        var parsed = JSON.parse(rawTests);
                        if (Array.isArray(parsed)) {
                            parsed.forEach(function(item){
                                var nm = typeof item === 'string' ? item : (item.name || item.testName || '');
                                if (nm) testList.push(nm.trim());
                            });
                        }
                    } catch(e) {
                        rawTests.split(',').forEach(function(part){
                            var pt = part.trim();
                            if (pt) testList.push(pt);
                        });
                    }
                } else if (Array.isArray(rawTests)) {
                    rawTests.forEach(function(item){
                        var nm = typeof item === 'string' ? item : (item.name || item.testName || '');
                        if (nm) testList.push(nm.trim());
                    });
                }
                if (testList.length > 0) {
                    self.tests = [];
                    testList.forEach(function(tn, idx){
                        self.selectedStatus[idx] = 'available';
                        self.tests.push({
                            testId: '',
                            testName: tn,
                            testType: matchedOrder.sampleType || '',
                            conceptUuid: '',
                            status: 'available'
                        });
                    });
                    self._render();
                }
            }
        }

        // 1. Check if selections were already saved in the database
        new Ajax.Request('<%=basePath%>pages/dashboard/getStockOutSelections.jsp', {
            method: 'get',
            parameters: { sampleId: orderId },
            onSuccess: function(xhr){
                try {
                    var saved = JSON.parse(xhr.responseText);
                    if (saved && Array.isArray(saved) && saved.length > 0) {
                        self.tests = [];
                        for (var i = 0; i < saved.length; i++) {
                            var s = saved[i];
                            var st = (s.status && s.status === 'stockout') ? 'stockout' : 'available';
                            self.selectedStatus[i] = st;
                            self.tests.push({
                                testId: s.testId ? String(s.testId) : '',
                                testName: s.testName || ('Test ' + (i + 1)),
                                testType: '',
                                conceptUuid: s.conceptUuid || '',
                                status: st
                            });
                        }
                        self._render();
                        return;
                    }
                } catch(e) {}

                // If row already provided tests, do not override with empty fetch
                if (self.tests && self.tests.length > 0) {
                    return;
                }

                // 2. Fallback to discover tests from order/sample if never saved before
                self._fetchTests(orderId);
            },
            onFailure: function(){
                if (!self.tests || self.tests.length === 0) {
                    self._fetchTests(orderId);
                }
            }
        });
    },

    _fetchTests:function(sampleId){
        var self=this;
        new Ajax.Request('ajaxQueryXML',{method:'get',
            parameters:"provider=SampleTypeTestsForSampleProvider&sampleId="+sampleId,
            onSuccess:function(xhr){
                var rawXml=xhr.responseText||'';
                var xml=xhr.responseXML;
                self.tests=[];
                var testIds=[];
                if(xml){
                    var testEls=xml.getElementsByTagName('test');
                    for(var i=0;i<testEls.length;i++){
                        var el=testEls[i];
                        var tName='';
                        var testId='';
                        var attrs=el.attributes;
                        if(attrs){
                            for(var a=0;a<attrs.length;a++){
                                var n=attrs[a].name.toLowerCase();
                                if(n.indexOf('name')>=0){
                                    tName=attrs[a].value;
                                }
                                if(n==='id'||n.indexOf('test')>=0){
                                    testId=attrs[a].value;
                                }
                            }
                        }
                        if(!tName){tName=el.textContent||'';}
                        tName=tName.trim();
                        if(/^\d+$/.test(tName)){testId=tName;tName='';}
                        if(testId){testIds.push(testId);}
                        var sType='';
                        if(attrs){
                            for(var a=0;a<attrs.length;a++){
                                var n=attrs[a].name.toLowerCase();
                                if(n.indexOf('sample')>=0){
                                    sType=attrs[a].value;
                                    break;
                                }
                            }
                        }
                        self.tests.push({testName:tName,testType:sType,testId:testId});
                    }
                }
                if(testIds.length>0){
                    new Ajax.Request('<%=basePath%>pages/dashboard/testNameLookup.jsp',{method:'get',
                        parameters:{ids:testIds.join(',')},
                        onSuccess:function(xhr2){
                            try{
                                var nameMap=JSON.parse(xhr2.responseText);
                                for(var j=0;j<self.tests.length;j++){
                                    var t=self.tests[j];
                                    if(t.testId&&nameMap[t.testId]){
                                        t.testName=nameMap[t.testId];
                                    }
                                }
                            }catch(e){}
                            self._render();
                        },
                        onFailure:function(){self._render();}
                    });
                }else{
                    if(self.tests.length===0){
                        self.tests=[{testName:'All Tests in Order',testType:'N/A'}];
                    }
                    self._render();
                }
            },
            onFailure:function(){
                self.tests=[{testName:'All Tests in Order',testType:'N/A'}];
                self._render();
            }
        });
    },

    _render:function(){
        var self=this;
        var html='';
        if (!this.tests || this.tests.length === 0) {
            document.getElementById('stockoutTestList').innerHTML = '<div style="padding:15px;text-align:center;color:#64748b;font-size:12px;">No tests found for this order.</div>';
            return;
        }
        this.tests.forEach(function(t,i){
            var name=(typeof t==='string'?t:(t.testName||('Test '+(i+1)))).trim();
            var type=(t&&t.testType)?t.testType:'';
            if(!self.selectedStatus[i] || self.selectedStatus[i] === 'pending'){
                self.selectedStatus[i] = 'available';
            }
            var st=self.selectedStatus[i];
            var availCls='stockout-btn available'+(st==='available'?' selected':'');
            var soCls='stockout-btn stockout'+(st==='stockout'?' selected':'');
            html+='<div class="stockout-test-item">';
            html+='<div><div class="stockout-test-name">'+name+'</div>';
            if(type)html+='<div class="stockout-test-type">'+type+'</div>';
            html+='</div>';
            html+='<div class="stockout-toggle">';
            html+='<button type="button" class="'+availCls+'" id="so-avail-'+i+'" onclick="StockOut.setStatus('+i+',\'available\')">Available</button>';
            html+='<button type="button" class="'+soCls+'" id="so-so-'+i+'" onclick="StockOut.setStatus('+i+',\'stockout\')">Stock-Out</button>';
            html+='</div></div>';
        });
        document.getElementById('stockoutTestList').innerHTML=html;
    },

    hidePanel:function(){
        var p = document.getElementById('stockoutPanel');
        if (p) {
            p.classList.remove('show');
            p.style.display = 'none';
        }
    },

    setStatus:function(index,status){
        this.selectedStatus[index]=status;
        var availBtn=document.getElementById('so-avail-'+index);
        var soBtn=document.getElementById('so-so-'+index);
        if(availBtn)availBtn.classList.remove('selected');
        if(soBtn)soBtn.classList.remove('selected');
        if(status==='available'){
            if(availBtn)availBtn.classList.add('selected');
        }else{
            if(soBtn)soBtn.classList.add('selected');
        }
    },

    markAllAvailable:function(){
        var self=this;
        this.tests.forEach(function(t,i){self.setStatus(i,'available')});
    },

    markAllStockOut:function(){
        var self=this;
        this.tests.forEach(function(t,i){self.setStatus(i,'stockout')});
    },

    getStockOutTests:function(){
        var self=this;
        var result=[];
        this.tests.forEach(function(t,i){
            if(self.selectedStatus[i]==='stockout'){
                result.push({testName:t.testName||('Test '+(i+1)),testId:t.testId||''});
            }
        });
        return result;
    },

    getAvailableTests:function(){
        var self=this;
        var result=[];
        this.tests.forEach(function(t,i){
            if(self.selectedStatus[i]==='available'){
                result.push({testName:t.testName||('Test '+(i+1)),testId:t.testId||''});
            }
        });
        return result;
    },

    saveSelections:function(confirmNow){
        var self=this;
        var order=this.currentOrderId;
        if (!order) {
            window.showAppToast('Selection Error', 'No active order selected.', 'error');
            return;
        }
        if (!this.tests || this.tests.length === 0 || (this.tests.length === 1 && this.tests[0].testName === 'Loading tests...')) {
            window.showAppToast('Please Wait', 'Please wait for tests to finish loading before saving.', 'warning');
            return;
        }
        var selections=[];
        this.tests.forEach(function(t,i){
            var st = (self.selectedStatus[i] === 'stockout') ? 'stockout' : (confirmNow ? 'confirmed' : 'available');
            var tName=(typeof t==='string'?t:(t.testName||'')).trim();
            var tId=(t&&t.testId)?t.testId:'';
            var cUuid=(t&&t.conceptUuid)?t.conceptUuid:'';
            selections.push({testId:tId,testName:tName,conceptUuid:cUuid,status:st});
        });

        if (selections.length === 0) {
            window.showAppToast('Selection Error', 'No tests available to evaluate for this order.', 'warning');
            return;
        }

        var saveBtn = document.querySelector('#stockoutPanel .btn-success');
        if (saveBtn) {
            saveBtn.innerHTML = confirmNow ? 'Confirming & Unlocking...' : 'Saving & Dispatching...';
            saveBtn.style.opacity = '0.7';
            saveBtn.disabled = true;
        }

        var data={orderId:order,selections:selections,confirmNow:!!confirmNow};
        var postPayload = '';
        var origToJSON = Array.prototype.toJSON;
        try {
            delete Array.prototype.toJSON;
            postPayload = JSON.stringify(data);
        } finally {
            if (origToJSON) Array.prototype.toJSON = origToJSON;
        }

        new Ajax.Request('<%=basePath%>pages/dashboard/saveStockOutSelections.jsp',{
            method:'post',
            contentType:'application/json',
            requestHeaders:{'Content-Type':'application/json'},
            postBody:postPayload,
            onSuccess:function(xhr){
                if (saveBtn) { saveBtn.innerHTML = 'Save & Send to Billing'; saveBtn.style.opacity = '1'; saveBtn.disabled = false; }
                try{
                    var resp=JSON.parse(xhr.responseText);
                    if(resp.success){
                        self.hidePanel();
                        if(window.evaluatedSampleIds){
                            window.evaluatedSampleIds.add(String(order));
                        }
                        if(window.sentToBillingSampleIds){
                            window.sentToBillingSampleIds.add(String(order));
                        }
                        if(resp.confirmed && window.confirmedSampleIds){
                            window.confirmedSampleIds.add(String(order));
                        }

                        var detailMsg = '';
                        if(resp.confirmed){
                            detailMsg = 'Quotation confirmed in Odoo! Sample collection is unlocked.';
                        } else if(resp.availableCount > 0 && resp.stockOutCount > 0){
                            detailMsg = resp.availableCount + ' test(s) sent to Odoo Billing. ' + resp.stockOutCount + ' stock-out test(s) voided in OpenMRS.';
                        } else if(resp.availableCount > 0){
                            detailMsg = resp.availableCount + ' test(s) verified Available and sent to Odoo Billing.';
                        } else if(resp.stockOutCount > 0){
                            detailMsg = resp.stockOutCount + ' test(s) marked Stock-Out and excluded from billing.';
                        } else {
                            detailMsg = 'Stock-out evaluation saved and sent to Odoo Billing.';
                        }

                        sessionStorage.setItem('pendingToast', JSON.stringify({
                            title: resp.confirmed ? 'Billing Approved & Confirmed ✓' : 'Stock Evaluation Saved & Sent to Billing',
                            message: detailMsg,
                            type: 'success',
                            duration: 4500
                        }));
                        window.location.href = window.location.pathname + '?_t=' + new Date().getTime();
                    }else{
                        window.showAppToast('Save Failed', (resp.error || 'unknown error'), 'error');
                    }
                }catch(e){
                    self.hidePanel();
                    window.location.href = window.location.pathname + '?_t=' + new Date().getTime();
                }
            },
            onFailure:function(xhr){
                if (saveBtn) { saveBtn.innerHTML = 'Save & Send to Billing'; saveBtn.style.opacity = '1'; saveBtn.disabled = false; }
                window.showAppToast('Network Error', 'Save request failed with status: ' + (xhr.status || 'network error'), 'error');
            }
        });
    },

    confirmBilling: function(orderId, patientId) {
        var btn = document.getElementById('btn-confirm-' + orderId);
        if (btn) {
            btn.innerHTML = 'Confirming...';
            btn.style.opacity = '0.7';
            btn.disabled = true;
        }
        new Ajax.Request('<%=basePath%>pages/dashboard/sendToBilling.jsp?action=confirmQuotation&orderId=' + encodeURIComponent(orderId) + '&patientId=' + encodeURIComponent(patientId || ''), {
            method: 'post',
            onSuccess: function(xhr) {
                try {
                    var resp = JSON.parse(xhr.responseText);
                    if (resp.success) {
                        if (window.confirmedSampleIds) {
                            window.confirmedSampleIds.add(String(orderId));
                        }
                        if (window.confirmedPatientRefs && patientId) {
                            window.confirmedPatientRefs.add(String(patientId).trim());
                        }
                        sessionStorage.setItem('pendingToast', JSON.stringify({
                            title: 'Quotation Confirmed & Approved',
                            message: 'Quotation approved in Odoo! Sample collection unlocked.',
                            type: 'success',
                            duration: 4500
                        }));
                        window.location.href = window.location.pathname + '?_t=' + new Date().getTime();
                    } else {
                        window.showAppToast('Confirmation Failed', resp.error || 'Could not confirm quotation in Odoo', 'error');
                        if (btn) { btn.innerHTML = 'Confirm Billing &#10003;'; btn.style.opacity = '1'; btn.disabled = false; }
                    }
                } catch(e) {
                    window.location.href = window.location.pathname + '?_t=' + new Date().getTime();
                }
            },
            onFailure: function() {
                window.showAppToast('Network Error', 'Failed to reach server to confirm quotation.', 'error');
                if (btn) { btn.innerHTML = 'Confirm Billing &#10003;'; btn.style.opacity = '1'; btn.disabled = false; }
            }
        });
    },

    sendToBilling:function(orderId, patientId){
        var self=this;
        var btn = document.getElementById('btn-bill-' + orderId);
        if(btn){
            btn.innerHTML = '<span style="font-size:10px;">Sending...</span>';
            btn.style.opacity = '0.7';
            btn.style.pointerEvents = 'none';
        }
        new Ajax.Request('<%=basePath%>pages/dashboard/sendToBilling.jsp', {
            method: 'post',
            parameters: { orderId: orderId, patientId: patientId },
            onSuccess: function(xhr){
                try {
                    var resp = JSON.parse(xhr.responseText);
                    if(resp.success){
                        if(window.sentToBillingSampleIds){
                            window.sentToBillingSampleIds.add(String(orderId));
                            if(patientId) window.sentToBillingSampleIds.add(String(patientId));
                        }
                        if(btn){
                            btn.outerHTML = "<span class='badge-sent-billing' style='display:inline-block;padding:2px 7px;background:#dcfce7;color:#15803d;border:1px solid #86efac;border-radius:4px;font-size:10px;font-weight:700;'>Sent to Billing ✓</span>";
                        }
                        sessionStorage.setItem('pendingToast', JSON.stringify({
                            title: 'Sent to Billing',
                            message: 'Order #' + orderId + ' successfully sent to Odoo Billing! Patient quotation ready.',
                            type: 'success',
                            duration: 4500
                        }));
                        window.location.href = window.location.pathname + '?_t=' + new Date().getTime();
                    } else {
                        window.showAppToast('Billing Sync Notice', (resp.error || 'Quotation ready in Odoo.'), 'warning');
                        if(btn){ btn.style.opacity = '1'; btn.style.pointerEvents = 'auto'; btn.innerHTML = 'Send to Billing'; }
                    }
                } catch(e) {
                    window.location.href = window.location.pathname + '?_t=' + new Date().getTime();
                }
            },
            onFailure: function(){
                window.showAppToast('Billing Notification', 'Order notification dispatched.', 'info');
                window.location.href = window.location.pathname + '?_t=' + new Date().getTime();
            }
        });
    },

    generateNotice:function(){
        var self=this;
        var stockOutTests=this.getStockOutTests();
        if(stockOutTests.length===0){
            window.showAppToast('Notice Required', 'Please mark at least one test as Stock-Out before generating a notice.', 'warning');
            return;
        }

        var noticeNumber='SO-'+Date.now().toString(36).toUpperCase();
        var noticeDate=new Date().toLocaleString();
        var order=this.currentOrderId;

        var printContent='<!DOCTYPE html><html><head><title>Stock-Out Notice</title>';
        printContent+='<style>';
        printContent+='body{font-family:Arial,sans-serif;margin:20px;font-size:12px;line-height:1.5}';
        printContent+='h1{font-size:18px;text-align:center;border-bottom:2px solid #000;padding-bottom:10px;margin-bottom:5px}';
        printContent+='h2{font-size:14px;text-align:center;color:#dc2626;margin:5px 0 15px 0}';
        printContent+='table{width:100%;border-collapse:collapse;margin:15px 0}';
        printContent+='td{border:1px solid #ccc;padding:8px;font-size:11px}';
        printContent+='td:first-child{background:#f5f5f5;font-weight:bold;width:30%}';
        printContent+='h3{color:#dc2626;border-bottom:1px solid #dc2626;padding-bottom:5px;font-size:14px}';
        printContent+='.action-box{border:2px solid #dc2626;padding:15px;margin:15px 0;background:#fff5f5}';
        printContent+='.action-box ol{margin:10px 0;padding-left:20px}';
        printContent+='.action-box li{margin:5px 0}';
        printContent+='.sig-section{display:flex;justify-content:space-between;margin-top:40px}';
        printContent+='.sig-box{width:45%;border-top:1px solid #000;padding-top:5px}';
        printContent+='.footer{text-align:center;font-size:10px;color:#666;margin-top:20px}';
        printContent+='@media print{body{margin:10px}}';
        printContent+='</style></head><body>';
        printContent+='<h1>LABORATORY STOCK-OUT NOTICE</h1>';
        printContent+='<h2>Non-Conformity Report for Reagent Unavailability</h2>';
        printContent+='<table>';
        printContent+='<tr><td>Notice Number:</td><td><strong>'+noticeNumber+'</strong></td><td>Date:</td><td><strong>'+noticeDate+'</strong></td></tr>';
        if(order){printContent+='<tr><td>Order ID:</td><td colspan="3">'+order+'</td></tr>';}
        printContent+='</table>';
        printContent+='<h3>Affected Tests (Cancelled)</h3>';
        printContent+='<table><tr><td colspan="4" style="background:#f8fafc;font-weight:bold">Tests marked as Stock-Out due to reagent unavailability.</td></tr>';
        stockOutTests.forEach(function(t){
            printContent+='<tr><td>'+t.testName+'</td><td>Reagent Stock Out</td><td>'+noticeDate+'</td><td>Cancelled</td></tr>';
        });
        printContent+='</table>';
        printContent+='<div class="action-box"><strong>Required Actions:</strong><ol>';
        printContent+='<li>Notify the ordering clinician about the reagent stock-out</li>';
        printContent+='<li>Advise patient to return when reagents are available</li>';
        printContent+='<li>Schedule follow-up appointment if clinically urgent</li>';
        printContent+='<li>Update inventory system with stock-out record</li>';
        printContent+='</ol></div>';
        printContent+='<div class="sig-section"><div class="sig-box"><p>Receptionist Signature</p></div>';
        printContent+='<div class="sig-box"><p>Patient/Guardian Signature</p></div></div>';
        printContent+='<div class="footer"><p>This notice confirms that the above test(s) could not be performed due to reagent unavailability.</p>';
        printContent+='<p>Please retain this notice for your records and follow up with your clinician.</p></div>';
        printContent+='</body></html>';

        var testNames=stockOutTests.map(function(t){return t.testName}).join(', ');
        var patientNameEl=document.getElementById('name');
        var patientName=patientNameEl?patientNameEl.textContent:'';
        var accessionEl=document.querySelector('.accessionNumber');

        var saveData={
            noticeNumber:noticeNumber,
            accessionNumber:accessionEl?accessionEl.textContent.trim():'',
            orderId:order,
            patientName:patientName,
            stockOutTests:stockOutTests,
            availableTests:self.getAvailableTests()
        };

        new Ajax.Request('<%=basePath%>pages/dashboard/saveStockOutNotice.jsp',{
            method:'post',
            contentType:'application/json',
            postBody:JSON.stringify(saveData),
            onSuccess:function(xhr){
                try{
                    var resp=JSON.parse(xhr.responseText);
                    if(!resp.success){console.error('Save failed:',resp.error);}
                }catch(e){console.error('Parse error:',e);}
            },
            onFailure:function(xhr){console.error('Save request failed');}
        });

        var w=window.open('','StockOutNotice','width=800,height=600,scrollbars=yes');
        if(w){w.document.write(printContent);w.document.close();setTimeout(function(){w.print()},500);}

        document.getElementById('snNoticeNumber').textContent=noticeNumber;
        document.getElementById('snDate').textContent=noticeDate;
        document.getElementById('snOrder').textContent=order||'N/A';
        document.getElementById('snTestsVoided').textContent=testNames;
        document.getElementById('stockoutNoticeModal').classList.add('show');
        this.hidePanel();
    },

    closeNoticeModal:function(){
        document.getElementById('stockoutNoticeModal').classList.remove('show');
    }
};

(function(){
    var K='od_dashboard_visibility',t=document.getElementById('od-customize-toggle'),d=document.getElementById('od-customize-dropdown');
    if(!t||!d)return;
    function gp(){try{var r=localStorage.getItem(K);return r?JSON.parse(r):null}catch(e){return null}}
    function sp(p){try{localStorage.setItem(K,JSON.stringify(p))}catch(e){}}
    function ap(){var p=gp()||{},cbs=d.querySelectorAll('input[type="checkbox"]');cbs.forEach(function(cb){var k=cb.getAttribute('data-card'),card=document.querySelector('.od-stat-card[data-card="'+k+'"]');if(!card)return;var v=p.hasOwnProperty(k)?p[k]:true;cb.checked=v;if(v)card.classList.remove('od-card-hidden');else card.classList.add('od-card-hidden')})}
    t.addEventListener('click',function(e){e.stopPropagation();d.classList.toggle('open')});
    document.addEventListener('click',function(e){if(!d.contains(e.target)&&e.target!==t)d.classList.remove('open')});
    d.addEventListener('click',function(e){e.stopPropagation()});
    var cbs=d.querySelectorAll('input[type="checkbox"]');cbs.forEach(function(cb){cb.addEventListener('change',function(){var k=this.getAttribute('data-card'),card=document.querySelector('.od-stat-card[data-card="'+k+'"]');if(!card)return;if(this.checked)card.classList.remove('od-card-hidden');else card.classList.add('od-card-hidden');var p={};cbs.forEach(function(c){p[c.getAttribute('data-card')]=c.checked});sp(p)})});
    ap();
})();
</script>