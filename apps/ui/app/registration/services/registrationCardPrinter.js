'use strict';

angular.module('bahmni.registration')
    .factory('registrationCardPrinter', ['printer', '$http', function (printer, $http) {
        var print = function (templatePath, patient, obs, encounterDateTime, location) {
            templatePath = templatePath || "views/nolayoutfound.html";

            var sendPrint = function (branding) {
                printer.print(templatePath, {
                    patient: patient,
                    today: new Date(),
                    obs: obs || {},
                    encounterDateTime: encounterDateTime,
                    location: location,
                    branding: branding || {}
                });
            };

            $http.get('/backup-api/branding', { ignoreErrors: true }).then(function (res) {
                sendPrint(res.data);
            }, function () {
                $http.get('/bahmni_config/openmrs/apps/branding.json', { ignoreErrors: true }).then(function (res2) {
                    sendPrint(res2.data);
                }, function () {
                    sendPrint({});
                });
            });
        };

        return {
            print: print
        };
    }]);
