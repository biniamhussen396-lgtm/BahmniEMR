'use strict';

angular.module('bahmni.registration')
    .controller('CRTriageVisitController', ['$window', '$scope', '$rootScope', '$state', '$bahmniCookieStore', 'patientService', 'encounterService', '$stateParams', 'spinner', '$timeout', '$q', 'appService', 'openmrsPatientMapper', 'contextChangeHandler', 'messagingService', 'sessionService', 'visitService', '$location', '$translate',
        'auditLogService', 'formService', 'observationsService', 'ngDialog', '$http',
        function ($window, $scope, $rootScope, $state, $bahmniCookieStore, patientService, encounterService, $stateParams, spinner, $timeout, $q, appService, openmrsPatientMapper, contextChangeHandler, messagingService, sessionService, visitService, $location, $translate, auditLogService,
            formService, observationsService, ngDialog, $http) {
            var vm = this;
            var patientUuid = $stateParams.patientUuid;
            var extensions = appService.getAppDescriptor().getExtensions("org.bahmni.registration.conceptSetGroup.observations", "crconfig");
            var formExtensions = appService.getAppDescriptor().getExtensions("org.bahmni.registration.conceptSetGroup.observations", "crforms");
            var locationUuid = sessionService.getLoginLocationUuid();
            var loginLocationUuid = $bahmniCookieStore.get(Bahmni.Common.Constants.locationCookieName).uuid;
            var defaultVisitType = $rootScope.regEncounterConfiguration.getDefaultVisitType(loginLocationUuid);
            defaultVisitType = defaultVisitType || appService.getAppDescriptor().getConfigValue('defaultVisitType');

            var selectedProvider = $rootScope.currentProvider;
            $scope.currentProvider = $rootScope.currentProvider || {};
            var regEncounterTypeUuid = $rootScope.regEncounterConfiguration.encounterTypes[Bahmni.Registration.Constants.registrationEncounterType];
            var visitLocationUuid = $rootScope.visitLocation;
            $scope.noOfPatients = 0;
            var femaleVisitTypes = appService.getAppDescriptor().getConfigValue("femaleOnlyVisitType")
            $scope.visitTypeFilter = function (visitTp) {
                var filteredStatus = _.filter(femaleVisitTypes, function (arrMem) {
                    return arrMem === visitTp.name;
                });
                if ($scope.patient.gender == 'M' && filteredStatus.length > 0) {
                    return false;
                }
                else {
                    return true;
                }
            }
            $scope.destOPD = false;
            $scope.$watch('observations[0].groupMembers',function(){
                try{
                    if($scope.observations[0].groupMembers.filter(obs => obs.label== "Destination OPD")[0].value) $scope.destOPD = true
                    else $scope.destOPD = false
                }
                catch{}
                },true)
            var getPatient = function () {
                var deferred = $q.defer();
                patientService.get(patientUuid).then(function (openMRSPatient) {
                    deferred.resolve(openMRSPatient);
                    $scope.patient = openmrsPatientMapper.map(openMRSPatient);
                    var p = (openMRSPatient && openMRSPatient.patient) ? openMRSPatient.patient : (openMRSPatient || {});
                    var person = p.person || (openMRSPatient && openMRSPatient.person);
                    $scope.patient.name = (person && person.names && person.names[0] && person.names[0].display) || p.display || ($scope.patient && $scope.patient.name) || '';
                    $scope.patient.uuid = p.uuid || patientUuid;
                    $scope.patient.identifier = (p.identifiers && p.identifiers[0] && p.identifiers[0].identifier) || ($scope.patient && $scope.patient.identifier) || '';
                });
                return deferred.promise;
            };
            var getActivePatients = async function () {
                var params = {
                    q: "emrapi.centralTriage.activePatientForOPDs",
                    visit_type_uuid: $scope.selectedVisitType.uuid
                }
                var response = await $http.get("/openmrs/ws/rest/v1/bahmnicore/sql", {
                    method: "GET",
                    params: params,
                    withCredentials: true
                });
                var noOfPatient = response.data[0].Number_of_Active_Patient_per_OPD
                return noOfPatient

            };
            var getPatientPerVisit = async function () {
                var params = {
                    q: "emrapi.centraltriage.noOfPatientPerVisit"
                }
                var response = await $http.get("/openmrs/ws/rest/v1/bahmnicore/sql", {
                    method: "GET",
                    params: params,
                    withCredentials: true
                });

                return response.data;

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

            $scope.updatePatientImage = function (image) {
                var updateImagePromise = patientService.updateImage($scope.patient.uuid, image.replace("data:image/jpeg;base64,", ""));
                spinner.forPromise(updateImagePromise);
                return updateImagePromise;
            };
            var getFee = function (fee_type) {
                var params = {
                    name: fee_type
                };
                return $http.get(Bahmni.Common.Constants.conceptSearchByFullNameUrl, {
                    method: "GET",
                    params: params,
                    withCredentials: true
                });
            };

            var findObservationValue = function (observations, conceptName) {
                if (!observations) return null;
                for (var i = 0; i < observations.length; i++) {
                    var obs = observations[i];
                    if (obs.concept && obs.concept.name === conceptName) {
                        return obs.value;
                    }
                    if (obs.groupMembers && obs.groupMembers.length > 0) {
                        var val = findObservationValue(obs.groupMembers, conceptName);
                        if (val) return val;
                    }
                }
                return null;
            };

            var save = function () {
                var triageTypeObs = findObservationValue($scope.observations, "Triage Type");
                var isOphthalmic = false;
                if (triageTypeObs) {
                    var display = typeof triageTypeObs === 'object' ? (triageTypeObs.display || triageTypeObs.name || '') : triageTypeObs;
                    isOphthalmic = display.toLowerCase().indexOf('ophthalmic') !== -1;
                }
                var feeType = isOphthalmic ? "Ophta Registration Fee" : "Regular Registration Fee";

                return getFee(feeType).then(function (r) {
                    $rootScope.newCRPat = false;
                    $scope.encounter = {
                        patientUuid: $scope.patient.uuid,
                        locationUuid: locationUuid,
                        encounterTypeUuid: regEncounterTypeUuid,
                        orders: [],
                        drugOrders: [],
                        extensions: {}
                    };

                    if (r.data.results && r.data.results[0]) {
                        $scope.encounter.orders.push({
                            concept: {
                                name: r.data.results[0].display,
                                uuid: r.data.results[0].uuid
                            },
                            commentToFulfiller: "",
                            urgency: "ROUTINE"
                        });
                    }

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
                        var messageParams = { encounterUuid: response.data.encounterUuid, encounterType: response.data.encounterType };
                        auditLogService.log(patientUuid, 'EDIT_ENCOUNTER', messageParams, 'MODULE_LABEL_REGISTRATION_KEY');
                        var visitType, visitTypeUuid;
                        visitTypeUuid = $scope.selectedVisitType.uuid;
                        visitService.getVisitType().then(function (response) {
                            visitType = _.find(response.data.results, function (type) {
                                if (type.uuid === visitTypeUuid) {
                                    return type;
                                }
                                else {
                                    return $scope.selectedVisitType;
                                }
                            });
                        });
                    });
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
                    patient: patientUuid, includeInactive: false, v: "custom:(uuid,location:(uuid))"
                }).then(function (response) {
                    var results = (response.data && response.data.results) ? response.data.results : [];
                    var matchedVisit = null;
                    if (results.length > 0) {
                        if (visitLocationUuid) {
                            matchedVisit = _.find(results, function (result) {
                                return result.location && result.location.uuid === visitLocationUuid;
                            });
                        }
                        matchedVisit = matchedVisit || results[0];
                    }

                    var hasActiveVisit = !!matchedVisit;
                    vm.visitUuid = hasActiveVisit ? matchedVisit.uuid : "";
                    $scope.canCloseVisit = isUserPrivilegedToCloseVisit() && hasActiveVisit;
                });
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
                if (forwardUrl != null) {
                    $window.location.href = appService.getAppDescriptor().formatUrl(forwardUrl, { 'patientUuid': patientUuid });
                } else {
                    $state.transitionTo($state.current, $state.params, {
                        reload: true,
                        inherit: false,
                        notify: true
                    });
                }
                messagingService.showMessage('info', 'REGISTRATION_LABEL_SAVED');
            };
            var closeVisit = function () {
                if (vm != undefined) {
                    visitService.getVisitSummary(vm.visitUuid).then(function (response) {
                        var visitSummary = response.data;
                        visitService.endVisit(vm.visitUuid).then(function () {
                            var messageParams = { visitUuid: visitSummary.visitUuid, visitType: visitSummary.visitType };
                            auditLogService.log(patientUuid, 'CLOSE_VISIT', messageParams, 'MODULE_LABEL_REGISTRATION_KEY');
                        });
                    });
                }



            }
            $scope.saveConfirmation = function () {
                closeVisit(); //Close the Visit
                $scope.visitControl.startVisit($scope.selectedVisitType);
                var visitDetails = { patient: patientUuid, visitType: $scope.selectedVisitType.uuid, location: visitLocationUuid };
                visitService.createVisit(visitDetails).then(function (response) {
                })
                ngDialog.close();
                $scope.submit();
            }
            $scope.cancel = function () {
                ngDialog.close();
            }


            $scope.visitControl = new Bahmni.Common.VisitControl(
                $rootScope.regEncounterConfiguration.getVisitTypesAsArray(),
                defaultVisitType, encounterService, $translate, visitService
            );
            $scope.startVisit = async function (selectedVisit) {
                var noOfPatients = 0;
                if (selectedVisit != undefined) {
                    selectedVisit = selectedVisit.split(" --- ");
                    $scope.selectedVisitType = $scope.visitControl.visitTypes.filter(function (visitType) {
                        return visitType.name === selectedVisit[0];
                    })[0];
                    noOfPatients = await getActivePatients();
                    if (noOfPatients < 35) {
                        closeVisit(); //Close the Central Triage Visit
                        $scope.visitControl.startVisit($scope.selectedVisitType);
                        var visitDetails = { patient: patientUuid, visitType: $scope.selectedVisitType.uuid, location: visitLocationUuid };
                        visitService.createVisit(visitDetails).then(function (response) {
                        })
                        ngDialog.close();
                        $scope.submit();
                    }

                    else {
                        //Pop up when the numbe exceed
                        ngDialog.close()
                        $scope.noOfPatients = noOfPatients;
                        $scope.exceededPatienPopupHandler()
                    }


                    ngDialog.close()
                }
            }
            $scope.exceededPatienPopupHandler = function () {
                $scope.dialog = ngDialog.open({
                    template: 'views/patientExceedPopUp.html',
                    className: 'ngdialog-theme-default',
                    scope: $scope
                });
                noOfPatient = 0;
                $('body').addClass('show-controller-back');
            }

            $scope.visitControl.onStartVisit = function () {
                $scope.startVisit($scope.visitControl.selectedVisit);
            };
            var getFemaleOnlyVisitTypes = function () {
                var params = {
                    q: "emrapi.visitTypes.femaleOnlyVisitTypes"
                }
                return $http.get('/openmrs/ws/rest/v1/bahmnicore/sql', {
                    method: "GET",
                    params: params,
                    withCredentials: true
                });

            };

            $scope.startVisits = async function () {
                var noOfPatientsPerVisit = await getPatientPerVisit();
                if ($scope.patient.gender == 'M') {
                    var femaleOnlyVisitTypes = getFemaleOnlyVisitTypes().then(function (response) {
                        $scope.femaleOnlyVisitTypes = response.data;
                        $scope.currentVisitTypes = [];
                        if ($scope.femaleOnlyVisitTypes) {
                            for (var i = 0; i < $scope.femaleOnlyVisitTypes.length; i++) {
                                for (var j=0; j<$scope.visitControl.visitTypes.length; j++) {
                                    if ($scope.femaleOnlyVisitTypes[i].name == $scope.visitControl.visitTypes[j].name) {
                                        $scope.currentVisitTypes[j]= $scope.visitControl.visitTypes[j];                      
                                    }
                                }
                            }
                           $scope.filterredVisitTypes = [];
                           for (var k = 0; k < $scope.visitControl.visitTypes.length; k++) {
                            if ($scope.currentVisitTypes[k]!=$scope.visitControl.visitTypes[k]) {
                                $scope.filterredVisitTypes.push($scope.visitControl.visitTypes[k])
                            }
                           }
                           $scope.visitControl.visitTypes = $scope.filterredVisitTypes;
                        }
    
                    });
                }
                
                $scope.visitControl.visitTypes.forEach(visitType => {
                    noOfPatientsPerVisit.forEach(noOfPatientPerVisit => {
                        if (noOfPatientPerVisit.name == visitType.name) {
                            visitType.patientPerVisit = noOfPatientPerVisit.NoOfPatientPerVisit;
                        }
                    });
                    if (visitType.patientPerVisit == undefined) {
                        visitType.patientPerVisit = 0;
                    }
                });
                return validate().then($scope.startVisitPopUpHandler);
            };

            $scope.startVisitPopUpHandler = function () {
                $scope.dialog = ngDialog.open({
                    template: 'views/startVisitPopUp.html',
                    className: 'test ngdialog-theme-default',
                    scope: $scope
                });
                $('body').addClass('show-controller-back');
            };

            $scope.submit = function () {
                return save().then(afterSave);
            };

            $scope.today = function () {
                return new Date();
            };



            $scope.changeVisits = function () {
                $scope.encounter = {
                    patientUuid: $scope.patient.uuid,
                    locationUuid: locationUuid,
                    encounterTypeUuid: regEncounterTypeUuid,
                    orders: [],
                    drugOrders: [],
                    extensions: {}
                };
                $scope.encounter.observations = $scope.observations;
                $scope.encounter.observations = new Bahmni.Common.Domain.ObservationFilter().filter($scope.encounter.observations);
                addFormObservations($scope.encounter.observations);
                var createPromise = encounterService.create($scope.encounter);
                spinner.forPromise(createPromise);
                return createPromise.then(function (response) {
                    var messageParams = { encounterUuid: response.data.encounterUuid, encounterType: response.data.encounterType };
                    auditLogService.log(patientUuid, 'EDIT_ENCOUNTER', messageParams, 'MODULE_LABEL_REGISTRATION_KEY');
                    afterSave();
                });

            }

            $scope.enterVisitDetails = $rootScope.newCRPat;
            $scope.disableFormSubmitOnEnter = function () {
                $('.visit-patient').find('input').keypress(function (e) {
                    if (e.which === 13) { // Enter key = keycode 13
                        return false;
                    }
                });
            };

            var getConceptSet = function () {
                var visitType = $scope.encounterConfig.getVisitTypeByUuid($scope.visitTypeUuid);
                $scope.context = { visitType: visitType, patient: $scope.patient };
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