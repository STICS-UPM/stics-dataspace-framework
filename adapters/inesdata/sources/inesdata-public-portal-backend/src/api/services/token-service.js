const axios = require('axios');

const tokenData = {
  accessToken: null,
  refreshToken: null,
  expiresIn: null,
  refreshExpiresIn: null,
  obtainedAt: null,
  refreshObtainedAt: null
};

const getTokenFromAuthServer = async () => {
  try {
    const params = new URLSearchParams();
    params.append('grant_type', 'password');
    params.append('client_id', process.env.TOKEN_CLIENT_ID);
    params.append('username', process.env.TOKEN_USERNAME);
    params.append('password', process.env.TOKEN_PASSWORD);

    const tokenUrl = `${process.env.KEYCLOAK_BASE_URL}/protocol/openid-connect/token`;

    const response = await axios.post(tokenUrl, params);
    const data = response.data;

    tokenData.accessToken = data.access_token;
    tokenData.refreshToken = data.refresh_token;
    tokenData.expiresIn = data.expires_in; // expires_in is in seconds
    tokenData.refreshExpiresIn = data.refresh_expires_in; // refresh_expires_in is in seconds
    tokenData.obtainedAt = Date.now(); // store the time the token was obtained
    tokenData.refreshObtainedAt = Date.now(); // store the time the refresh token was obtained

    return data;
  } catch (error) {
    console.error('Error obtaining token from auth server:', error);
    throw new Error('Failed to obtain token from auth server');
  }
};

const refreshToken = async () => {
  try {
    const params = new URLSearchParams();
    params.append('grant_type', 'refresh_token');
    params.append('client_id', process.env.TOKEN_CLIENT_ID);
    params.append('refresh_token', tokenData.refreshToken);

    const tokenUrl = `${process.env.KEYCLOAK_BASE_URL}/protocol/openid-connect/token`;

    const response = await axios.post(tokenUrl, params);
    const data = response.data;

    tokenData.accessToken = data.access_token;
    tokenData.refreshToken = data.refresh_token;
    tokenData.expiresIn = data.expires_in;
    tokenData.refreshExpiresIn = data.refresh_expires_in;
    tokenData.obtainedAt = Date.now();

    return data;
  } catch (error) {
    console.error('Error refreshing token:', error);
    throw new Error('Failed to refresh token');
  }
};

const getAccessToken = async () => {
  try {
    if (!tokenData.accessToken || !tokenData.refreshToken) {
      await getTokenFromAuthServer();
    } else {
      const currentTime = Date.now();
      const accessTokenExpired = (currentTime - tokenData.obtainedAt) / 1000 > tokenData.expiresIn;
      const refreshTokenExpired = (currentTime - tokenData.refreshObtainedAt) / 1000 > tokenData.refreshExpiresIn;

      if (refreshTokenExpired) {
        await getTokenFromAuthServer();
      } else if (accessTokenExpired) {
        await refreshToken();
      }
    }

    return tokenData.accessToken;
  } catch (error) {
    console.error('Error getting access token:', error);
    throw new Error('Failed to get access token');
  }
};

module.exports = {
  getTokenFromAuthServer,
  refreshToken,
  getAccessToken
};
