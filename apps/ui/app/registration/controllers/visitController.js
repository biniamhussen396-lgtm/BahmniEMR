'use strict';

angular.module('bahmni.registration')
    .controller('VisitController', ['$http','$window', '$scope', '$rootScope', '$state', '$bahmniCookieStore', 'patientService', 'encounterService', '$stateParams', 'spinner', '$timeout', '$q', 'appService', 'openmrsPatientMapper', 'contextChangeHandler', 'messagingService', 'sessionService', 'visitService', '$location', '$translate',
        'auditLogService', 'formService', 'dispositionService',
        function ($http,$window, $scope, $rootScope, $state, $bahmniCookieStore, patientService, encounterService, $stateParams, spinner, $timeout, $q, appService, openmrsPatientMapper, contextChangeHandler, messagingService, sessionService, visitService, $location, $translate, auditLogService, formService, dispositionService) {
            var vm = this;
            var patientUuid = $stateParams.patientUuid;
            var extensions = appService.getAppDescriptor().getExtensions("org.bahmni.registration.conceptSetGroup.observations", "config");
            var formExtensions = appService.getAppDescriptor().getExtensions("org.bahmni.registration.conceptSetGroup.observations", "forms");
            var locationUuid = sessionService.getLoginLocationUuid();
            var payment_config = appService.getAppDescriptor().getConfigValue("paymentConfig")
            var selectedProvider = $rootScope.currentProvider;
            $scope.currentProvider = $rootScope.currentProvider || {};
            var regEncounterTypeUuid = $rootScope.regEncounterConfiguration.encounterTypes[Bahmni.Registration.Constants.registrationEncounterType];
            var visitLocationUuid = $rootScope.visitLocation;
            var redirectToDashboard = false;
            $scope.enableDashboardRedirect = _.some($rootScope.currentUser.privileges, {name: "app:clinical"}) && (appService.getAppDescriptor().getConfigValue("enableDashboardRedirect") || Bahmni.Registration.Constants.enableDashboardRedirect);

            var getPatient = function () {
                var deferred = $q.defer();
                patientService.get(patientUuid).then(function (openMRSPatient) {
                    deferred.resolve(openMRSPatient);
                    $scope.patient = openmrsPatientMapper.map(openMRSPatient);
                    var p = (openMRSPatient && openMRSPatient.patient) ? openMRSPatient.patient : (openMRSPatient || {});
                    var person = p.person || (openMRSPatient && openMRSPatient.person);
                    $scope.patient.name = (person && person.names && person.names[0] && person.names[0].display) || p.display || ($scope.patient && $scope.patient.name) || '';
                    $scope.patient.uuid = p.uuid || patientUuid;
                    if (person && person.attributes && Array.isArray(person.attributes)) {
                        person.attributes.forEach(function (x) {
                            if (x && x.display === "Is Emergency = true") {
                                fee_type = "Emergency Registration Fee";
                            }
                        });
                    }
                    
                    
                });
                return deferred.promise;
            };

            var getActiveEncounter = function () {
                var deferred = $q.defer();
                encounterService.find({
                    "patientUuid": patientUuid,
                    "providerUuids": !_.isEmpty($scope.currentProvider.uuid) ? [$scope.currentProvider.uuid] : null,
                    "includeAll": false,
                    locationUuid: locationUuid,
                    encounterTypeUuids: [regEncounterTypeUuid]
                }).then(function (response) {
                    deferred.resolve(response);
                    $scope.encounterUuid = response.data.encounterUuid;
                    $scope.observations = response.data.observations;
                });
                return deferred.promise;
            };

            var getAllForms = function () {
                var deferred = $q.defer();
                formService.getFormList($scope.encounterUuid)
                    .then(function (response) {
                        $scope.conceptSets = extensions.map(function (extension) {
                            return new Bahmni.ConceptSet.ConceptSetSection(extension, $rootScope.currentUser, {}, [], {});
                        });

                        $scope.observationForms = getObservationForms(formExtensions, response.data);
                        $scope.conceptSets = $scope.conceptSets.concat($scope.observationForms);

                        $scope.availableConceptSets = $scope.conceptSets.filter(function (conceptSet) {
                            return conceptSet.isAvailable($scope.context);
                        });
                        deferred.resolve(response.data);
                    });
                return deferred.promise;
            };

            $scope.hideFields = appService.getAppDescriptor().getConfigValue("hideFields");

            $scope.back = function () {
                $state.go('patient.edit');
            };

            $scope.updatePatientImage = function (image) {
                var updateImagePromise = patientService.updateImage($scope.patient.uuid, image.replace("data:image/jpeg;base64,", ""));
                spinner.forPromise(updateImagePromise);
                return updateImagePromise;
            };

            var fee_type = "Regular Registration Fee";
 
            var getFee = function () {                
                var params = {
                    name: fee_type
                };
                return $http.get(Bahmni.Common.Constants.conceptSearchByFullNameUrl, {
                    method: "GET",
                    params: params,
                    withCredentials: true
                });
            };

            var getOrderUuid = function () {
                var patientId = ($scope.patient && $scope.patient.primaryIdentifier && $scope.patient.primaryIdentifier.identifier) || ($scope.patient && $scope.patient.identifier) || '';
                var params = {
                    q: "bahmni.sqlGet.orderUuid",
                    id: patientId
                };
                return $http.get('/openmrs/ws/rest/v1/bahmnicore/sql', {
                    method: "GET",
                    params: params,
                    withCredentials: true
                }).catch(function () {
                    return { data: [] };
                });
            };

            var getEffectiveVisitTypeUuid = function () {
                if ($scope.visitTypeUuid) return $scope.visitTypeUuid;
                if (vm.visitTypeUuid) return vm.visitTypeUuid;
                var loginLocationCookie = $bahmniCookieStore.get(Bahmni.Common.Constants.locationCookieName);
                var curLocationUuid = (loginLocationCookie && loginLocationCookie.uuid) || locationUuid;
                var defaultVisitType = ($rootScope.regEncounterConfiguration && curLocationUuid) ? $rootScope.regEncounterConfiguration.getDefaultVisitType(curLocationUuid) : null;
                defaultVisitType = defaultVisitType || appService.getAppDescriptor().getConfigValue('defaultVisitType');
                if (defaultVisitType) {
                    return (typeof defaultVisitType === 'object') ? defaultVisitType.uuid : defaultVisitType;
                }
                return null;
            };

            var buildBaseEncounter = function (orders) {
                var encounter = {
                    patientUuid: $scope.patient.uuid,
                    locationUuid: locationUuid,
                    encounterTypeUuid: regEncounterTypeUuid,
                    orders: orders || [],
                    drugOrders: [],
                    extensions: {}
                };

                var effectiveVisitUuid = vm.visitUuid || $scope.visitUuid;
                if (effectiveVisitUuid) {
                    encounter.visitUuid = effectiveVisitUuid;
                }

                var effectiveVisitTypeUuid = getEffectiveVisitTypeUuid();
                if (effectiveVisitTypeUuid) {
                    encounter.visitTypeUuid = effectiveVisitTypeUuid;
                }

                if (visitLocationUuid || locationUuid) {
                    encounter.visitLocationUuid = visitLocationUuid || locationUuid;
                }

                return encounter;
            };
            
            var paymentWindow = payment_config["payment window"];
            var today = new Date();

            
            //paymentDate()
            var save = function () {
                return getOrderUuid().then(function (resp) {
                    var diffDays = paymentWindow + 1;
                    if (resp && resp.data && resp.data[0]) {
                        var orderDate = new Date(resp.data[0].date_created);
                        var diffTime = Math.abs(today - orderDate);
                        diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
                    }
                    if (diffDays >= paymentWindow && (!payment_config || !payment_config["disable billing"])) {
                        return getFee().then(function (r) {
                            var orders = [];
                            if (r.data && r.data.results && r.data.results[0]) {
                                orders.push({
                                    concept: {name: r.data.results[0].display, uuid: r.data.results[0].uuid},
                                    commentToFulfiller: "",
                                    urgency: "ROUTINE"
                                });
                            }
                            $scope.encounter = buildBaseEncounter(orders);

                            $bahmniCookieStore.put(Bahmni.Common.Constants.grantProviderAccessDataCookieName, selectedProvider, {
                                path: '/',
                                expires: 1
                            });

                            $scope.encounter.observations = $scope.observations;
                            $scope.encounter.observations = new Bahmni.Common.Domain.ObservationFilter().filter($scope.encounter.observations);

                            addFormObservations($scope.encounter.observations);

                            var createPromise = encounterService.create($scope.encounter);
                            spinner.forPromise(createPromise);
                            return createPromise.then(function (response) {
                                var messageParams = {encounterUuid: response.data.encounterUuid, encounterType: response.data.encounterType};
                                auditLogService.log(patientUuid, 'EDIT_ENCOUNTER', messageParams, 'MODULE_LABEL_REGISTRATION_KEY');
                                var visitType, visitTypeUuid;
                                visitTypeUuid = response.data.visitTypeUuid || getEffectiveVisitTypeUuid();
                                return visitService.getVisitType().then(function (response) {
                                    visitType = _.find(response.data.results, function (type) {
                                        if (type.uuid === visitTypeUuid) {
                                            return type;
                                        }
                                    });
                                    return response;
                                });
                            });
                        });
                    } else {
                        $scope.encounter = buildBaseEncounter([]);

                        $bahmniCookieStore.put(Bahmni.Common.Constants.grantProviderAccessDataCookieName, selectedProvider, {
                            path: '/',
                            expires: 1
                        });

                        $scope.encounter.observations = $scope.observations;
                        $scope.encounter.observations = new Bahmni.Common.Domain.ObservationFilter().filter($scope.encounter.observations);

                        addFormObservations($scope.encounter.observations);

                        var createPromise = encounterService.create($scope.encounter);
                        spinner.forPromise(createPromise);
                        return createPromise.then(function (response) {
                            var messageParams = {encounterUuid: response.data.encounterUuid, encounterType: response.data.encounterType};
                            auditLogService.log(patientUuid, 'EDIT_ENCOUNTER', messageParams, 'MODULE_LABEL_REGISTRATION_KEY');
                            var visitType, visitTypeUuid;
                            visitTypeUuid = response.data.visitTypeUuid || getEffectiveVisitTypeUuid();
                            return visitService.getVisitType().then(function (response) {
                                visitType = _.find(response.data.results, function (type) {
                                    if (type.uuid === visitTypeUuid) {
                                        return type;
                                    }
                                });
                                return response;
                            });
                        });
                    }
                });
            };

            var isUserPrivilegedToCloseVisit = function () {
                var applicablePrivs = [Bahmni.Common.Constants.closeVisitPrivilege, Bahmni.Common.Constants.deleteVisitsPrivilege];
                var userPrivs = _.map($rootScope.currentUser.privileges, function (privilege) {
                    return privilege.name;
                });
                return _.some(userPrivs, function (privName) {
                    return _.includes(applicablePrivs, privName);
                });
            };

            var searchActiveVisitsPromise = function () {
                return visitService.search({
                    patient: patientUuid, includeInactive: false, v: "custom:(uuid,location:(uuid,name),visitType:(uuid,name))"
                }).then(function (response) {
                    var results = (response.data && response.data.results) ? response.data.results : [];
                    var matchedVisit = null;
                    if (results.length > 0) {
                        $scope.visitTypeName = (results[0].visitType && results[0].visitType.name) ? results[0].visitType.name : '';
                        if (visitLocationUuid) {
                            matchedVisit = _.find(results, function (result) {
                                return result.location && result.location.uuid === visitLocationUuid;
                            });
                        }
                        matchedVisit = matchedVisit || results[0];
                    }

                    var hasActiveVisit = !!matchedVisit;
                    vm.visitUuid = hasActiveVisit ? matchedVisit.uuid : "";
                    $scope.visitUuid = vm.visitUuid;
                    if (hasActiveVisit && matchedVisit && matchedVisit.visitType) {
                        $scope.visitTypeUuid = matchedVisit.visitType.uuid;
                        vm.visitTypeUuid = matchedVisit.visitType.uuid;
                    }
                    $scope.canCloseVisit = isUserPrivilegedToCloseVisit() && hasActiveVisit;
                });
            };

            $scope.closeVisitIfDischarged = function () {
                visitService.getVisitSummary(vm.visitUuid).then(function (response) {
                    var visitSummary = response.data;
                    if (visitSummary.admissionDetails && !visitSummary.dischargeDetails) {
                        messagingService.showMessage("error", 'REGISTRATION_VISIT_CANNOT_BE_CLOSED');
                        var messageParams = {visitUuid: vm.visitUuid, visitType: visitSummary.visitType};
                        auditLogService.log(patientUuid, 'CLOSE_VISIT_FAILED', messageParams, 'MODULE_LABEL_REGISTRATION_KEY');
                    } else {
                        dispositionService.getDispositionByVisit(vm.visitUuid).then(function (dispResponse) {
                            var dispositions = dispResponse.data;
                            var hasEmergencyKeep = _.some(dispositions, function (d) {
                                return d.code === "EMERGENCY_KEEP" || d.conceptName === "Emergency keep" || d.preferredName === "Emergency keep";
                            });
                            if (hasEmergencyKeep) {
                                messagingService.showMessage("error", 'REGISTRATION_VISIT_CANNOT_BE_CLOSED');
                                var messageParams = {visitUuid: vm.visitUuid, visitType: visitSummary.visitType};
                                auditLogService.log(patientUuid, 'CLOSE_VISIT_FAILED_EMERGENCY_KEEP', messageParams, 'MODULE_LABEL_REGISTRATION_KEY');
                            } else {
                                closeVisit(visitSummary.visitType);
                            }
                        });
                    }
                });
            };

            var closeVisit = function (visitType) {
                var confirmed = $window.confirm($translate.instant("REGISTRATION_CONFIRM_CLOSE_VISIT"));
                if (confirmed) {
                    visitService.endVisit(vm.visitUuid).then(function () {
                        $location.url(Bahmni.Registration.Constants.patientSearchURL);
                        var messageParams = {visitUuid: vm.visitUuid, visitType: visitType};
                        auditLogService.log(patientUuid, 'CLOSE_VISIT', messageParams, 'MODULE_LABEL_REGISTRATION_KEY');
                    });
                }
            };
            $scope.getTranslatedPrimaryIdentifierInVisit = function (primaryIdentifierName) {
                var translatedName = Bahmni.Common.Util.TranslationUtil.translateAttribute(primaryIdentifierName, Bahmni.Common.Constants.registration, $translate);
                return translatedName;
            };
            $scope.getMessage = function () {
                return $scope.message;
            };

            var isObservationFormValid = function () {
                var valid = true;
                _.each($scope.observationForms, function (observationForm) {
                    if (valid && observationForm.component) {
                        var value = observationForm.component.getValue();
                        if (value.errors) {
                            messagingService.showMessage('error', "{{'REGISTRATION_FORM_ERRORS_MESSAGE_KEY' | translate }}");
                            valid = false;
                        }
                    }
                });
                return valid;
            };

            var validate = function () {
                var isFormValidated = mandatoryValidate();
                var deferred = $q.defer();
                var contxChange = contextChangeHandler.execute();
                var allowContextChange = contxChange["allow"];
                var errorMessage;
                if (!isObservationFormValid()) {
                    deferred.reject("Some fields are not valid");
                    return deferred.promise;
                }
                if (!allowContextChange) {
                    errorMessage = contxChange["errorMessage"] ? contxChange["errorMessage"] : 'REGISTRATION_LABEL_CORRECT_ERRORS';
                    messagingService.showMessage('error', errorMessage);
                    deferred.reject("Some fields are not valid");
                    return deferred.promise;
                } else if (!isFormValidated) { // This ELSE IF condition is to be deleted later.
                    errorMessage = "REGISTRATION_LABEL_ENTER_MANDATORY_FIELDS";
                    messagingService.showMessage('error', errorMessage);
                    deferred.reject("Some fields are not valid");
                    return deferred.promise;
                } else {
                    deferred.resolve();
                    return deferred.promise;
                }
            };

            // Start :: Registration Page validation
            // To be deleted later - Hacky fix only for Registration Page
            var mandatoryConceptGroup = [];
            var mandatoryValidate = function () {
                conceptGroupValidation($scope.observations);
                return isValid(mandatoryConceptGroup);
            };

            var conceptGroupValidation = function (observations) {
                var concepts = _.filter(observations, function (observationNode) {
                    return isMandatoryConcept(observationNode);
                });
                if (!_.isEmpty(concepts)) {
                    mandatoryConceptGroup = _.union(mandatoryConceptGroup, concepts);
                }
            };
            var isMandatoryConcept = function (observation) {
                if (!_.isEmpty(observation.groupMembers)) {
                    conceptGroupValidation(observation.groupMembers);
                } else {
                    return observation.conceptUIConfig && observation.conceptUIConfig.required;
                }
            };
            var isValid = function (mandatoryConcepts) {
                var concept = mandatoryConcepts.filter(function (mandatoryConcept) {
                    if (mandatoryConcept.hasValue()) {
                        return false;
                    }
                    if (mandatoryConcept instanceof Bahmni.ConceptSet.Observation &&
                        mandatoryConcept.conceptUIConfig && mandatoryConcept.conceptUIConfig.multiSelect) {
                        return false;
                    }
                    if (mandatoryConcept.isMultiSelect) {
                        return _.isEmpty(mandatoryConcept.getValues());
                    }
                    return !mandatoryConcept.value;
                });
                return _.isEmpty(concept);
            };
            // End :: Registration Page validation

            var afterSave = function () {
                var forwardUrl = appService.getAppDescriptor().getConfigValue("afterVisitSaveForwardUrl");
                var dashboardUrl = appService.getAppDescriptor().getConfigValue("dashboardUrl") || Bahmni.Registration.Constants.dashboardUrl;
                if (forwardUrl != null) {
                    $window.location.href = appService.getAppDescriptor().formatUrl(forwardUrl, {'patientUuid': patientUuid});
                } else if (dashboardUrl != null && redirectToDashboard) {
                    $window.location.href = appService.getAppDescriptor().formatUrl(dashboardUrl, {'patientUuid': patientUuid});
                } else {
                    $state.transitionTo($state.current, $state.params, {
                        reload: true,
                        inherit: false,
                        notify: true
                    });
                }
                messagingService.showMessage('info', 'REGISTRATION_LABEL_SAVED');
            };

            $scope.submit = function () {
                return validate().then(save).then(afterSave);
            };

            $scope.today = function () {
                return new Date();
            };

            $scope.disableFormSubmitOnEnter = function () {
                $('.visit-patient').find('input').keypress(function (e) {
                    if (e.which === 13) { // Enter key = keycode 13
                        return false;
                    }
                });
            };

            var getConceptSet = function () {
                var encConfig = $scope.encounterConfig || $rootScope.encounterConfig;
                var effectiveVisitTypeUuid = getEffectiveVisitTypeUuid();
                var visitType = (encConfig && encConfig.getVisitTypeByUuid && effectiveVisitTypeUuid) ? encConfig.getVisitTypeByUuid(effectiveVisitTypeUuid) : null;
                $scope.context = {visitType: visitType, patient: $scope.patient};
            };

            var getObservationForms = function (extensions, observationsForms) {
                var forms = [];
                var observations = $scope.observations || [];
                _.each(extensions, function (ext) {
                    var options = ext.extensionParams || {};
                    var observationForm = _.find(observationsForms, function (form) {
                        return (form.formName === options.formName || form.name === options.formName);
                    });
                    if (observationForm) {
                        var formUuid = observationForm.formUuid || observationForm.uuid;
                        var formName = observationForm.name || observationForm.formName;
                        var formVersion = observationForm.version || observationForm.formVersion;
                        forms.push(new Bahmni.ObservationForm(formUuid, $rootScope.currentUser, formName, formVersion, observations, formName, ext));
                    }
                });
                return forms;
            };

            $scope.isFormTemplate = function (data) {
                return data.formUuid;
            };

            var addFormObservations = function (observations) {
                if ($scope.observationForms) {
                    _.remove(observations, function (observation) {
                        return observation.formNamespace;
                    });
                    _.each($scope.observationForms, function (observationForm) {
                        if (observationForm.component) {
                            var formObservations = observationForm.component.getValue();
                            _.each(formObservations.observations, function (obs) {
                                observations.push(obs);
                            });
                        }
                    });
                }
            };

            spinner.forPromise($q.all([getPatient(), getActiveEncounter(), searchActiveVisitsPromise()])
                .then(function () {
                    getAllForms().then(function () {
                        getConceptSet();
                    });
                }));
        }]);
