'use strict';

angular.module('httpErrorInterceptor', [])
    .config(['$httpProvider', function ($httpProvider) {
        var interceptor = ['$rootScope', '$q', function ($rootScope, $q) {
            var serverErrorMessages = Bahmni.Common.Constants.serverErrorMessages;

            var showError = function (errorMessage) {
                var result = _.find(serverErrorMessages, function (listItem) {
                    return listItem.serverMessage === errorMessage;
                });
                if (_.isEmpty(result)) {
                    $rootScope.$broadcast('event:serverError', errorMessage);
                }
            };

            function stringAfter (value, searchString) {
                var indexOfFirstColon = value.indexOf(searchString);
                return value.substr(indexOfFirstColon + 1).trim();
            }

            function getServerError (message) {
                return stringAfter(message, ':');
            }

            function success (response) {
                return response;
            }

            function shouldRedirectToLogin (response) {
                var errorMessage = response.data.error ? response.data.error.message : response.data;
                if (errorMessage.search("Session timed out") > 0) {
                    return true;
                }
            }

            function error (response) {
                var data = response.data;
                var unexpectedError = "There was an unexpected issue on the server. Please try again";

                if (response.config && (response.config.ignoreErrors || (response.config.url && (response.config.url.indexOf('/openelis/') !== -1 || response.config.url.indexOf('/bahmnicore/disposition/') !== -1)))) {
                    return $q.reject(response);
                }

                if (response.status === 500) {
                    var errorMessage = data.error && data.error.message ? getServerError(data.error.message) : unexpectedError;
                    showError(errorMessage);
                } else if (response.status === 409) {
                    var errorMessage = data.error && data.error.message ? getServerError(data.error.message) : "Duplicate entry error";
                    showError(errorMessage);
                } else if (response.status === 0) {
                    showError("Could not connect to the server. Please check your connection and try again");
                } else if (response.status === 405) {
                    showError(unexpectedError);
                } else if (response.status === 400) {
                    var errorMessage = "Invalid request or validation error. Please verify the entered information.";
                    if (data && typeof data === 'object') {
                        errorMessage = (data.error && data.error.message) ? data.error.message : (data.error || data.localizedMessage || errorMessage);
                    } else if (typeof data === 'string') {
                        var msgMatch = data.match(/<b>Message<\/b>\s*([^<]+)/i);
                        if (msgMatch && msgMatch[1]) {
                            errorMessage = msgMatch[1].trim();
                        }
                    }
                    showError(errorMessage);
                } else if (response.status === 403) {
                    var errorMessage = data.error && data.error.message ? data.error.message : unexpectedError;
                    if (shouldRedirectToLogin(response)) {
                        $rootScope.$broadcast('event:auth-loginRequired');
                    } else {
                        showError(errorMessage);
                    }
                } else if (response.status === 404) {
                    if (!_.includes(response.config.url, "implementation_config") && !_.includes(response.config.url, "locale_") &&
                        !_.includes(response.config.url, "offlineMetadata") && !_.includes(response.config.url, "speciality") &&
                        !_.includes(response.config.url, "inactiveTests") &&
                        !_.includes(response.config.url, "LabLocationList") &&
                        !_.includes(response.config.url, "labLocationList") &&
                        !_.includes(response.config.url, "openelis") &&
                        !_.includes(response.config.url, "systemdate") &&
                        !_.includes(response.config.url, "cgi-bin") &&
                        !_.includes(response.config.url, "backup-api")) {
                        showError("The requested information does not exist");
                    }
                }
                return $q.reject(response);
            }

            return {
                response: success,
                responseError: error
            };
        }];
        $httpProvider.interceptors.push(interceptor);
    }]);
