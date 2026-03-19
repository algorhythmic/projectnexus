/**
 * Utility functions for Kalshi API authentication
 * 
 * Kalshi API requires RSA-PSS SHA-256 signature with the following:
 * - KALSHI-ACCESS-KEY header with API Key ID
 * - KALSHI-ACCESS-TIMESTAMP header with current timestamp in milliseconds
 * - KALSHI-ACCESS-SIGNATURE header with RSA-PSS signature of concatenated timestamp + HTTP method + path
 */

// Note: In a browser environment, we'd use a WebCrypto implementation
// For a Node.js environment, you would use the crypto module
// This is a simplified version for demonstration purposes

/**
 * Placeholder signature function for development
 * In production, this would use WebCrypto or crypto library to properly sign with RSA-PSS
 * 
 * @param message - Message to sign
 * @param privateKey - RSA private key
 * @returns Base64-encoded signature (placeholder)
 */
function generatePlaceholderSignature(message: string, privateKey: string): string {
  // This is just a placeholder implementation for development/testing
  // Do not use in production - implement proper RSA-PSS signing
  const encoder = new TextEncoder();
  const data = encoder.encode(message + '_' + privateKey.substring(0, 10));
  return btoa(String.fromCharCode(...new Uint8Array(data)));
}

/**
 * Generate Kalshi API authentication headers
 * 
 * @param apiKeyId - The Kalshi API Key ID
 * @param privateKey - The RSA private key in PEM format
 * @param method - The HTTP method (GET, POST, etc)
 * @param path - The request path (e.g., "/v2/markets")
 * @returns An object containing all required Kalshi authentication headers
 */
export function generateKalshiAuthHeaders(
  apiKeyId: string,
  privateKey: string,
  method: string,
  path: string
): Record<string, string> {
  try {
    // Current timestamp in milliseconds
    const timestamp = Date.now().toString();
    
    // Message to sign is timestamp + HTTP method + path
    const message = timestamp + method + path;
    
    // In a real implementation, this would use the WebCrypto API or a suitable library
    // We're using a placeholder signature for demonstration
    // This is just a placeholder - in production, we would generate a proper RSA-PSS signature
    const signature = generatePlaceholderSignature(message, privateKey);
    
    // Return all required headers
    return {
      'KALSHI-ACCESS-KEY': apiKeyId,
      'KALSHI-ACCESS-TIMESTAMP': timestamp,
      'KALSHI-ACCESS-SIGNATURE': signature
    };
  } catch (error) {
    console.error('Failed to generate Kalshi authentication headers:', error);
    throw new Error('Failed to generate Kalshi authentication headers. Check your API credentials.');
  }
}

/**
 * Create fetch request options with Kalshi authentication headers
 * 
 * @param apiKeyId - The Kalshi API Key ID
 * @param privateKey - The RSA private key in PEM format
 * @param method - The HTTP method (GET, POST, etc)
 * @param path - The request path (e.g., "/v2/markets")
 * @param options - Additional fetch options
 * @returns Request options with Kalshi authentication headers
 */
export function createKalshiAuthenticatedRequest(
  apiKeyId: string,
  privateKey: string,
  method: string,
  path: string,
  options: RequestInit = {}
): RequestInit {
  const headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    ...generateKalshiAuthHeaders(apiKeyId, privateKey, method, path),
    ...options.headers
  };
  
  return {
    method,
    headers,
    ...options
  };
}

/**
 * Validates if a private key is in valid RSA PEM format
 * 
 * @param privateKey - The RSA private key to validate
 * @returns Whether the key appears to be valid
 */
export function isValidRSAPrivateKey(privateKey: string): boolean {
  // Basic format validation - more thorough validation would require actually
  // parsing the key which is beyond the scope of a client-side validation
  return (
    privateKey.includes('-----BEGIN PRIVATE KEY-----') ||
    privateKey.includes('-----BEGIN RSA PRIVATE KEY-----')
  ) && (
    privateKey.includes('-----END PRIVATE KEY-----') ||
    privateKey.includes('-----END RSA PRIVATE KEY-----')
  );
}
