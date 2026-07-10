public class Demo
{
    void run(String version)
    {
        assertTrue(version.equals("UNKNOWN") || version.equals("${project.version}") || version.matches("\\d+\\.\\d+\\.\\d+.*"), "MAVEN_VERSION should be 'UNKNOWN', '${project.version}', or match semantic version pattern (x.y.z), got: " + version);
    }
}
