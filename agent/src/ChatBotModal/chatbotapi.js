import axios from "axios";
const BASE_URL_CHATBOT = `https://data.vikaspedia.in/`;
export const CONTENT_TYPE_MULTIPART_FORM_DATA = "multipart/form-data";

const axiosInstance = (
  baseURL,
  token,
  contentType = "application/json;charset=utf-8"
) => {
  const instance = axios.create({
    baseURL,
    timeout: 120000,
    headers: {
      "Content-Type": contentType,
      "Access-Control-Allow-Origin": "*",
    },
  });

  instance.interceptors.request.use((config) => {
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  instance.interceptors.response.use(
    (response) => response,
    (error) => Promise.reject(error)
  );

  return instance;
};

export const chatBotBaseApi = async (data) => {
  const path = `/chatbot`;
  const res = await axiosInstance(BASE_URL_CHATBOT).post(path, data);
  return res && res.data ? res.data : null;
};

export const generateChatBotAudio = async (data) => {
  const path = `/generateCBAudio`;
  const res = await axiosInstance(
    BASE_URL_CHATBOT,
    null,
    CONTENT_TYPE_MULTIPART_FORM_DATA
  ).post(path, data);
  return res && res.data ? res.data : null;
};

export const chatBotGenerateSummary = async (data) => {
  const path = `/generateCBSummary`;
  const res = await axiosInstance(
    BASE_URL_CHATBOT,
    null,
    CONTENT_TYPE_MULTIPART_FORM_DATA
  ).post(path, data);
  return res && res.data ? res.data : null;
};

export const getAdminTransilateKey = async (popularSearchInput, lgn) => {
  const path = `https://inputtools.google.com/request?text=${popularSearchInput}&itc=${lgn}-t-i0-und&num=13&cp=0&cs=1&ie=utf-8&oe=utf-8&app=demopage`;
  const res = await axios.get(path);
  return res && res.data ? res.data : null;
};

// use base URLS From API Constant
// create function for calling api method using above axios instance
// refer axios services
