
function order(div, orderArray, generateLink, getColumns, alwaysValidate, showPriorityColumn) {
     this.div = div;
     this.orderArray = orderArray;
     this.columns = getColumns(showPriorityColumn, alwaysValidate);
         this.indexesOfNonSearchableColumns = function(){
                var indexes = [];

                jQuery.each(this.columns, function(id, column){

                    //we shouldn't add the id for the column if column.searchable is null.
                    // It assumes that we don't need to specify searchable property when the column is searchable
                    if (column.searchable == false){
                        indexes.push(column.index != null ? column.index : id);
                    }
                });

                return indexes;
             }
function formatTAT(order) {
    if (!order) return "-";
    if (order.tat) return order.tat;
    if (order.turnAroundTime) return order.turnAroundTime;
    var start = null;
    if (order.collectionDate) {
        start = new Date(order.collectionDate);
    } else if (order.collectionDateString) {
        start = new Date(order.collectionDateString);
    } else if (order.enteredDate) {
        start = new Date(order.enteredDate);
    }
    if (!start || isNaN(start.getTime())) {
        return "-";
    }
    var end = null;
    if (order.isCompleted && order.completedDate) {
        end = new Date(order.completedDate);
    } else if (order.isCompleted && order.lastupdated) {
        end = new Date(order.lastupdated);
    } else {
        end = new Date();
    }
    var diffMs = end.getTime() - start.getTime();
    if (diffMs < 0) return "< 1m";
    var totalMins = Math.floor(diffMs / 60000);
    var days = Math.floor(totalMins / 1440);
    var hours = Math.floor((totalMins % 1440) / 60);
    var mins = totalMins % 60;
    if (days > 0) return days + "d " + hours + "h";
    if (hours > 0) return hours + "h " + mins + "m";
    return Math.max(1, mins) + "m";
}

    this.orderList = function (){

            if (this.orders) {
                return this.orders;
            }

            this.orders = jQuery.map(this.orderArray, function(order, i) {
                order.id= i;
                order.link = generateLink(order, alwaysValidate);
                order.name = order.firstName + (order.middleName ? " " + order.middleName : "") + (order.lastName ? " " +order.lastName : "");
                order.tat = formatTAT(order);
                return order;
            });

            return this.orders;
         };
}

function generateLinkForPrint(order){
    var printMessage = jQuery("#translatedColumnNames").attr("data-link-print");
    var printIcon = '<img id="actionIcon" src="images/print.svg" title="'+ printMessage +'">';
    return "<a id='print' target='_blank' href='ReportPrint.do?type=patient&report=patientHaitiClinical&accessionDirect="+ order.accessionNumber +"&patientNumberDirect=" + order.stNumber + "'>"+printIcon+"</a>";
}


function generateAllLinksForOrder(order, alwaysValidate){
    if(order.accessionNumber == null){
        var linkSample = jQuery("#translatedColumnNames").attr("data-link-collectSample");
        var sOrder = String(order.orderId || "").trim();
        var checkInSet = function(s, val) {
            if (!s || !val) return false;
            if (s.has && s.has(val)) return true;
            if (Array.isArray(s) && s.indexOf(val) !== -1) return true;
            return false;
        };
        var isConfirmed = order.hasPaid ||
                          checkInSet(window.confirmedSampleIds, sOrder) ||
                          (order.sampleId && checkInSet(window.confirmedSampleIds, String(order.sampleId).trim())) ||
                          (order.stNumber && checkInSet(window.confirmedPatientRefs, String(order.stNumber).trim()));

        if(isConfirmed){
            return "<a class='btn-collect' href='SamplePatientEntry.do?id="+ order.orderId +"&patientId=" + order.stNumber + "' style='background:#059669;color:#fff;padding:3px 8px;border-radius:4px;font-weight:600;text-decoration:none;font-size:11px;'>"+linkSample+"</a>";
        }else{
            var testNamesArr=order.testNames;
            if(typeof testNamesArr==='string'){try{testNamesArr=JSON.parse(testNamesArr)}catch(e){testNamesArr=[]}}
            var isEvaluated = checkInSet(window.evaluatedSampleIds, sOrder) ||
                              (order.sampleId && checkInSet(window.evaluatedSampleIds, String(order.sampleId).trim()));
            var isSent = checkInSet(window.sentToBillingSampleIds, sOrder) ||
                         (order.sampleId && checkInSet(window.sentToBillingSampleIds, String(order.sampleId).trim()));
            var notPaidBadge = "<span class='not-paid-badge' style='display:inline-block;padding:2px 6px;background:#fef3c7;color:#b45309;border:1px solid #f59e0b;border-radius:3px;font-size:10px;font-weight:bold;margin-right:6px;'>Not Paid</span>";
            var editIconSvg = "<span class='stockout-edit-icon' onclick='StockOut.showPanel(\""+order.orderId+"\")' title='Edit selections before billing' style='cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;vertical-align:middle;color:#475569;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;margin-left:4px;transition:all .15s;' onmouseover='this.style.background=\"#e2e8f0\"' onmouseout='this.style.background=\"#f1f5f9\"'><svg style=\"width:12px;height:12px;\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.2\"><path d=\"M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7\"/><path d=\"M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z\"/></svg></span>";

            if(isSent){
                return notPaidBadge +
                       "<span class='badge-sent-billing' style='display:inline-block;padding:3px 7px;background:#dcfce7;color:#15803d;border:1px solid #86efac;border-radius:4px;font-size:10px;font-weight:700;white-space:nowrap;'>Sent to Billing &#10003;</span>" +
                       "<a href='javascript:void(0)' id='btn-confirm-"+order.orderId+"' class='btn-confirm-billing' onclick='StockOut.confirmBilling(\""+order.orderId+"\",\""+(order.stNumber||"")+"\")' title='Click to approve quotation in Odoo and unlock sample collection' style='display:inline-block;padding:3px 8px;background:#059669;color:#ffffff;border-radius:4px;font-size:10px;font-weight:700;margin-left:4px;text-decoration:none;box-shadow:0 1px 2px rgba(0,0,0,0.05);white-space:nowrap;' onmouseover='this.style.background=\"#047857\"' onmouseout='this.style.background=\"#059669\"'>Confirm Billing &#10003;</a>" +
                       editIconSvg;
            }else if(isEvaluated){
                return notPaidBadge +
                       "<a href='javascript:void(0)' id='btn-bill-"+order.orderId+"' class='btn-send-billing' onclick='StockOut.sendToBilling(\""+order.orderId+"\",\""+(order.stNumber||"")+"\")' style='display:inline-block;padding:3px 8px;background:#2563eb;color:#ffffff;border-radius:4px;font-size:11px;font-weight:600;text-decoration:none;box-shadow:0 1px 2px rgba(0,0,0,0.05);white-space:nowrap;' onmouseover='this.style.background=\"#1d4ed8\"' onmouseout='this.style.background=\"#2563eb\"'>Send to Billing</a>" +
                       editIconSvg;
            }else{
                return notPaidBadge +
                       "<span class='stockout-link' onclick='StockOut.showPanel(\""+order.orderId+"\")' style='cursor:pointer;color:#dc2626;font-weight:600;font-size:11px;text-decoration:underline;white-space:nowrap;'>Stock-Out Check</span>";
            }
        }
    }
    var resultMessage = jQuery("#translatedColumnNames").attr("data-link-result");
    var resultIcon = '<img id="actionIcon" src="images/result.svg" title="'+resultMessage+'">';
    var enterResultLink;
    if(order.sampleType == null) {
        enterResultLink = "<a id='result' href='AccessionResults.do?accessionNumber=" + order.accessionNumber + "&referer=LabDashboard" + "'>" + resultIcon + "</a>";
    } else {
        var sampleType = order.sampleType.replace(/'/g, '%27');
       enterResultLink = "<a id='result' href='AccessionResults.do?accessionNumber=" + order.accessionNumber + "&sampleType=" + sampleType + "&referer=LabDashboard" + "'>" + resultIcon + "</a>";
    }

    var labelMessage = jQuery("#translatedColumnNames").attr("data-link-label");
    var labelIcon = '<img style="cursor: pointer" id="actionIcon" src="images/sampleLabelPrint.png" title="'+labelMessage+'">';
    var sampleLabelLink = "<a class='label' accessionNumber='"+order.accessionNumber+"' stNumber='"+order.stNumber+"' collectionDate='"+order.collectionDate+"' collectionDateStr='"+order.collectionDateString+"'>"+labelIcon+"</a>";


    if(alwaysValidate){
        //TODO: &type= is required in the url because of a bug I can't find the source of. The bug causes people without
        var validateMessage = jQuery("#translatedColumnNames").attr("data-link-validate");
        var validateIcon = '<img id="actionIcon" src="images/validate.svg" title="'+validateMessage+'">';
        var validationLink;
        if(order.sampleType == null) {
            validationLink = "<a id='validate' href='ResultValidationForAccessionNumber.do?accessionNumber=" + order.accessionNumber + "&patientId=" + order.stNumber + "&referer=LabDashboard&type=&test='>" + validateIcon + "</a>";
        } else {
            var sampleType = order.sampleType.replace(/'/g, '%27');
            validationLink  = "<a id='validate' href='ResultValidationForAccessionNumber.do?accessionNumber=" + order.accessionNumber + "&patientId=" + order.stNumber + "&sampleType=" + sampleType + "&referer=LabDashboard&type=&test='>" + validateIcon + "</a>";
        }
        return sampleLabelLink + " | " + enterResultLink + " | " + validationLink + " | " + generateLinkForPrint(order);
    }
    return sampleLabelLink + " | " + enterResultLink + " | " + generateLinkForPrint(order);
}

function getColumnsForTodayOrder(showPriorityColumn, alwaysValidate) {
    if(showPriorityColumn) {
        if (alwaysValidate) {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"sampleType", name:jQuery("#translatedColumnNames").attr("data-sampleType"), field:"sampleType", searchable:true, sortable:true, index:4, editor:Slick.Editors.Text, width:120, minWidth:95, maxWidth:140},
                {id:"priority", name:jQuery("#translatedColumnNames").attr("data-priority"), field:"priority", searchable:true, sortable:true, index:5, editor:Slick.Editors.Text, width:75, minWidth:65, maxWidth:90},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"pendingValidationCount", name:jQuery("#translatedColumnNames").attr("data-pendingValidation"), field:"pendingValidationCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:125, minWidth:100, maxWidth:145},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:9, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:10, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"isCompleted", name:jQuery("#translatedColumnNames").attr("data-completed"), field:"isCompleted", sortable:true, cssClass:"cell-title", index:11, formatter:Slick.Formatters.YesNo, searchable:false, width:80, minWidth:65, maxWidth:95},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:12, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:13, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
        else {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"sampleType", name:jQuery("#translatedColumnNames").attr("data-sampleType"), field:"sampleType", searchable:true, sortable:true, index:4, editor:Slick.Editors.Text, width:120, minWidth:95, maxWidth:140},
                {id:"priority", name:jQuery("#translatedColumnNames").attr("data-priority"), field:"priority", searchable:true, sortable:true, index:5, editor:Slick.Editors.Text, width:75, minWidth:65, maxWidth:90},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:9, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"isCompleted", name:jQuery("#translatedColumnNames").attr("data-completed") || "Completed", field:"isCompleted", sortable:true, cssClass:"cell-title", index:10, formatter:Slick.Formatters.YesNo, searchable:false, width:80, minWidth:65, maxWidth:95},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:11, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:12, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
    } else {
        if (alwaysValidate) {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:4, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"pendingValidationCount", name:jQuery("#translatedColumnNames").attr("data-pendingValidation"), field:"pendingValidationCount", sortable:true, editor:Slick.Editors.Text, index:5, searchable:false, width:125, minWidth:100, maxWidth:145},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:8, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"isCompleted", name:jQuery("#translatedColumnNames").attr("data-completed"), field:"isCompleted", sortable:true, cssClass:"cell-title", index:9, formatter:Slick.Formatters.YesNo, searchable:false, width:80, minWidth:65, maxWidth:95},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:10, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:11, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
        else {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:4, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:5, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:7, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"isCompleted", name:jQuery("#translatedColumnNames").attr("data-completed") || "Completed", field:"isCompleted", sortable:true, cssClass:"cell-title", index:8, formatter:Slick.Formatters.YesNo, searchable:false, width:80, minWidth:65, maxWidth:95},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:9, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:10, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
    }
}

function getColumnsForBacklogOrder(showPriorityColumn, alwaysValidate) {
    if(showPriorityColumn) {
        if (alwaysValidate) {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"sampleType", name:jQuery("#translatedColumnNames").attr("data-sampleType"), field:"sampleType", searchable:true, sortable:true, index:4, editor:Slick.Editors.Text, width:120, minWidth:95, maxWidth:140},
                {id:"priority", name:jQuery("#translatedColumnNames").attr("data-priority"), field:"priority", searchable:true, sortable:true, index:5, editor:Slick.Editors.Text, width:75, minWidth:65, maxWidth:90},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"pendingValidationCount", name:jQuery("#translatedColumnNames").attr("data-pendingValidation"), field:"pendingValidationCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:125, minWidth:100, maxWidth:145},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:9, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:10, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:11, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:12, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
        else {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"sampleType", name:jQuery("#translatedColumnNames").attr("data-sampleType"), field:"sampleType", searchable:true, sortable:true, index:4, editor:Slick.Editors.Text, width:120, minWidth:95, maxWidth:140},
                {id:"priority", name:jQuery("#translatedColumnNames").attr("data-priority"), field:"priority", searchable:true, sortable:true, index:5, editor:Slick.Editors.Text, width:75, minWidth:65, maxWidth:90},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:9, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:10, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:11, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
    } else {
        if (alwaysValidate) {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:4, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"pendingValidationCount", name:jQuery("#translatedColumnNames").attr("data-pendingValidation"), field:"pendingValidationCount", sortable:true, editor:Slick.Editors.Text, index:5, searchable:false, width:125, minWidth:100, maxWidth:145},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:8, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:9, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:10, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
        else {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:4, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:5, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:7, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:8, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:9, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
    }
}

function getColumnsForSampleNotCollected(showPriorityColumn) {
    if(showPriorityColumn) {
        return [
            {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:0, width:95, minWidth:80, maxWidth:115},
            {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:1, editor:Slick.Editors.Text, width:220, minWidth:160},
            {id:"source", name:jQuery("#translatedColumnNames").attr("data-source"), field:"source", sortable:false, index:2, editor:Slick.Editors.Text, width:110, minWidth:90, maxWidth:130},
            {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:220, minWidth:160},
            {id:"sampleType", name:jQuery("#translatedColumnNames").attr("data-sampleType"), field:"sampleType", searchable:true, sortable:true, index:4, editor:Slick.Editors.Text, width:125, minWidth:100, maxWidth:145},
            {id:"priority", name:jQuery("#translatedColumnNames").attr("data-priority"), field:"priority", searchable:true, sortable:true, index:5, editor:Slick.Editors.Text, width:80, minWidth:70, maxWidth:95},
            {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:65, minWidth:55, maxWidth:80},
            {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:75, minWidth:65, maxWidth:90},
            {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:8, editor:Slick.Editors.Text, width:220, minWidth:160},
            {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:9, editor:Slick.Editors.Text, searchable:false, width:185, minWidth:160, maxWidth:240}
        ];
    } else {
        return [
            {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:0, width:95, minWidth:80, maxWidth:115},
            {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:1, editor:Slick.Editors.Text, width:220, minWidth:160},
            {id:"source", name:jQuery("#translatedColumnNames").attr("data-source"), field:"source", sortable:false, index:2, editor:Slick.Editors.Text, width:110, minWidth:90, maxWidth:130},
            {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:220, minWidth:160},
            {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:4, searchable:false, width:65, minWidth:55, maxWidth:80},
            {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:5, searchable:false, width:75, minWidth:65, maxWidth:90},
            {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:6, editor:Slick.Editors.Text, width:220, minWidth:160},
            {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:7, editor:Slick.Editors.Text, searchable:false, width:185, minWidth:160, maxWidth:240}
        ];
    }
}


// here referred Out test count column will be visible in dashboard
function getColumnsForTodayOrderWithReferredOutTestsCountColumn(showPriorityColumn, alwaysValidate) {
    if(showPriorityColumn) {
        if (alwaysValidate) {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"sampleType", name:jQuery("#translatedColumnNames").attr("data-sampleType"), field:"sampleType", searchable:true, sortable:true, index:4, editor:Slick.Editors.Text, width:120, minWidth:95, maxWidth:140},
                {id:"priority", name:jQuery("#translatedColumnNames").attr("data-priority"), field:"priority", searchable:true, sortable:true, index:5, editor:Slick.Editors.Text, width:75, minWidth:65, maxWidth:90},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"referredTestCount", name:jQuery("#translatedColumnNames").attr("data-referredTests"), field:"referredTestCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"pendingValidationCount", name:jQuery("#translatedColumnNames").attr("data-pendingValidation"), field:"pendingValidationCount", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:125, minWidth:100, maxWidth:145},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:9, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:10, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:11, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"isCompleted", name:jQuery("#translatedColumnNames").attr("data-completed"), field:"isCompleted", sortable:true, cssClass:"cell-title", index:12, formatter:Slick.Formatters.YesNo, searchable:false, width:80, minWidth:65, maxWidth:95},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:13, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:14, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
        else {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"sampleType", name:jQuery("#translatedColumnNames").attr("data-sampleType"), field:"sampleType", searchable:true, sortable:true, index:4, editor:Slick.Editors.Text, width:120, minWidth:95, maxWidth:140},
                {id:"priority", name:jQuery("#translatedColumnNames").attr("data-priority"), field:"priority", searchable:true, sortable:true, index:5, editor:Slick.Editors.Text, width:75, minWidth:65, maxWidth:90},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"referredTestCount", name:jQuery("#translatedColumnNames").attr("data-referredTests"), field:"referredTestCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:9, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:10, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"isCompleted", name:jQuery("#translatedColumnNames").attr("data-completed") || "Completed", field:"isCompleted", sortable:true, cssClass:"cell-title", index:11, formatter:Slick.Formatters.YesNo, searchable:false, width:80, minWidth:65, maxWidth:95},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:12, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:13, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
    } else {
        if (alwaysValidate) {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:4, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"referredTestCount", name:jQuery("#translatedColumnNames").attr("data-referredTests"), field:"referredTestCount", sortable:true, editor:Slick.Editors.Text, index:5, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"pendingValidationCount", name:jQuery("#translatedColumnNames").attr("data-pendingValidation"), field:"pendingValidationCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:125, minWidth:100, maxWidth:145},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:9, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"isCompleted", name:jQuery("#translatedColumnNames").attr("data-completed"), field:"isCompleted", sortable:true, cssClass:"cell-title", index:10, formatter:Slick.Formatters.YesNo, searchable:false, width:80, minWidth:65, maxWidth:95},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:11, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:12, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
        else {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:4, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"referredTestCount", name:jQuery("#translatedColumnNames").attr("data-referredTests"), field:"referredTestCount", sortable:true, editor:Slick.Editors.Text, index:5, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:8, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"isCompleted", name:jQuery("#translatedColumnNames").attr("data-completed") || "Completed", field:"isCompleted", sortable:true, cssClass:"cell-title", index:9, formatter:Slick.Formatters.YesNo, searchable:false, width:80, minWidth:65, maxWidth:95},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:10, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:11, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
    }
}


// here referred Out test count column will be visible in dashboard for backlog orders
function getColumnsForBacklogOrderWithReferredOutTestsCountColumn(showPriorityColumn, alwaysValidate) {
    if(showPriorityColumn) {
        if (alwaysValidate) {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"sampleType", name:jQuery("#translatedColumnNames").attr("data-sampleType"), field:"sampleType", searchable:true, sortable:true, index:4, editor:Slick.Editors.Text, width:120, minWidth:95, maxWidth:140},
                {id:"priority", name:jQuery("#translatedColumnNames").attr("data-priority"), field:"priority", searchable:true, sortable:true, index:5, editor:Slick.Editors.Text, width:75, minWidth:65, maxWidth:90},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"referredTestCount", name:jQuery("#translatedColumnNames").attr("data-referredTests"), field:"referredTestCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"pendingValidationCount", name:jQuery("#translatedColumnNames").attr("data-pendingValidation"), field:"pendingValidationCount", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:125, minWidth:100, maxWidth:145},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:9, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:10, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:11, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:12, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:13, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
        else {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"sampleType", name:jQuery("#translatedColumnNames").attr("data-sampleType"), field:"sampleType", searchable:true, sortable:true, index:4, editor:Slick.Editors.Text, width:120, minWidth:95, maxWidth:140},
                {id:"priority", name:jQuery("#translatedColumnNames").attr("data-priority"), field:"priority", searchable:true, sortable:true, index:5, editor:Slick.Editors.Text, width:75, minWidth:65, maxWidth:90},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"referredTestCount", name:jQuery("#translatedColumnNames").attr("data-referredTests"), field:"referredTestCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:9, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:10, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:11, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:12, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
    } else {
        if (alwaysValidate) {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:4, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"referredTestCount", name:jQuery("#translatedColumnNames").attr("data-referredTests"), field:"referredTestCount", sortable:true, editor:Slick.Editors.Text, index:5, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"pendingValidationCount", name:jQuery("#translatedColumnNames").attr("data-pendingValidation"), field:"pendingValidationCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:125, minWidth:100, maxWidth:145},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:8, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:9, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:10, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:11, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
        else {
            return [
                {id:"accessionNumber", name:jQuery("#translatedColumnNames").attr("data-accessionNumber"), field:"accessionNumber", sortable:true, index:0, editor:Slick.Editors.Text, width:130, minWidth:110, maxWidth:150},
                {id:"stNumber", name:jQuery("#translatedColumnNames").attr("data-patientID"), field:"stNumber", sortable:true, editor:Slick.Editors.Text, index:1, width:90, minWidth:75, maxWidth:110},
                {id:"name", name:jQuery("#translatedColumnNames").attr("data-patientName"), field:"name", sortable:true, index:2, editor:Slick.Editors.Text, width:180, minWidth:140},
                {id:"sectionNames", name:jQuery("#translatedColumnNames").attr("data-sectionNames"), field:"sectionNames", searchable:true, sortable:true, index:3, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"pendingTestCount", name:jQuery("#translatedColumnNames").attr("data-pendingTests"), field:"pendingTestCount", sortable:true, editor:Slick.Editors.Text, index:4, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"referredTestCount", name:jQuery("#translatedColumnNames").attr("data-referredTests"), field:"referredTestCount", sortable:true, editor:Slick.Editors.Text, index:5, searchable:false, width:95, minWidth:80, maxWidth:115},
                {id:"totalTestCount", name:jQuery("#translatedColumnNames").attr("data-total"), field:"totalTestCount", sortable:true, editor:Slick.Editors.Text, index:6, searchable:false, width:60, minWidth:50, maxWidth:75},
                {id:"tat", name:jQuery("#translatedColumnNames").attr("data-tat") || "TAT", field:"tat", sortable:true, editor:Slick.Editors.Text, index:7, searchable:false, width:70, minWidth:60, maxWidth:85},
                {id:"notes", name:jQuery("#translatedColumnNames").attr("data-notes"), field:"comments", sortable:true, index:8, searchable:false, editor:Slick.Editors.Text, width:170, minWidth:130},
                {id:"link", name:jQuery("#translatedColumnNames").attr("data-action"), field:"link", cssClass:"cell-title", formatter:formatter, index:9, editor:Slick.Editors.Text, searchable:false, width:125, minWidth:110, maxWidth:145},
                {id:"isPrinted", name:jQuery("#translatedColumnNames").attr("data-printed"), field:"isPrinted", sortable:true, cssClass:"cell-title", index:10, formatter:Slick.Formatters.Checkmark, searchable:false, width:65, minWidth:55, maxWidth:80}
            ];
        }
    }
}



function formatter(row, cell, value, columnDef, dataContext) {
    return value;
}
