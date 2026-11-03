'use strict';

angular.module('bahmni.common.domain')
    .service('commonNameDictionaryService', ['$http', '$rootScope', function ($http, $rootScope) {
        var self = this;

        this.getCommonNamesFor = function (searchTerm) {
            var url = Bahmni.Common.Constants.bahmniSearchUrl + "/personname";
            var queryWithoutTrailingSpaces = (searchTerm || '').trimLeft();
            return $http.get(url, {
                params: {q: queryWithoutTrailingSpaces, key: 'givenName'},
                withCredentials: true
            });
        };
        
    }]);
