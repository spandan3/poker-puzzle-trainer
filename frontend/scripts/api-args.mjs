// The one place openapi-typescript's arguments live (used by gen-api.mjs and check-api.mjs).
// --default-non-nullable false: request fields with defaults stay optional (partial PATCH bodies).
export const API_ARGS = ['--default-non-nullable', 'false']
