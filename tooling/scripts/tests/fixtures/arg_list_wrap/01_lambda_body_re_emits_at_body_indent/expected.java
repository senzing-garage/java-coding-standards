public class Demo
{
    public void run(java.util.Map<String, Object> dataSourceMap)
    {
        try {
            if (dataSourceMap != null) {
                dataSourceMap.entrySet().forEach(entry -> {
                    String key = entry.getKey();
                    if (key != null) {
                        key = key.trim().toUpperCase();
                    }
                    String value = entry.getValue().toString().trim();
                    dataSourceMap.put(key, value);
                });
            }
        } catch (NullPointerException e) {
            throw new RuntimeException(e);
        }
    }
}
