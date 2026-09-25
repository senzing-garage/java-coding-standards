public class T
{
    void t() throws Exception
    {
        try (BufferedReader br = new BufferedReader(isr))
        {
            for (String line = br.readLine(); line != null; line = br.readLine()) {
                consume(line);
            }
        }
    }
}
