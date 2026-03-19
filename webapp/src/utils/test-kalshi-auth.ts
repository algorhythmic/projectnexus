/**
 * Test utility for Kalshi API authentication
 * 
 * This is a simple script to test the Kalshi authentication flow
 * without requiring a full UI integration.
 */

import { generateKalshiAuthHeaders, isValidRSAPrivateKey } from './kalshi-auth';

/**
 * Test function to validate Kalshi API auth flow
 */
export async function testKalshiAuth(apiKeyId: string, privateKey: string): Promise<boolean> {
  console.log("Testing Kalshi API authentication...");
  
  // First validate the private key format
  const isValid = await isValidRSAPrivateKey(privateKey);
  if (!isValid) {
    console.error("Invalid RSA private key format");
    return false;
  }
  
  try {
    // Generate authentication headers for a test request
    const method = "GET";
    const path = "/v2/markets";
    const headers = generateKalshiAuthHeaders(apiKeyId, privateKey, method, path);
    
    console.log("Generated authentication headers:");
    console.log(headers);
    
    // In a real implementation, you would make an actual API request
    // and check the response status
    
    return true;
  } catch (error) {
    console.error("Error testing Kalshi authentication:", error);
    return false;
  }
}

// Example usage (if run directly):
// testKalshiAuth("<your-api-key-id>", "<your-private-key>");
