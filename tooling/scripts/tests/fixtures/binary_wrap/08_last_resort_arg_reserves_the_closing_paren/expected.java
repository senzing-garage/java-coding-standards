class Demo
{
    void m()
    {
        while (true) {
            while (true) {
                if (tryCount >= MAX_REINITIALIZE_COUNT) {
                    System.err.println(
                        "*** WARNING: Default configuration is constantly "
                            + "changing.  Could not reinitialize to the latest "
                            + "default configuration ID after " + tryCount
                            + " attempts.  activeConfigId=[ " + activeConfigId
                            + " ], defaultConfigId=[ " + defaultConfigId
                            + " ]");
                }
            }
        }
    }
}
